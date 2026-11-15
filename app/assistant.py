"""
AI Assistant and Natural Language Processing Engine.
Provides question intent classification, multi-turn follow-up context tracking,
local Ollama LLM reasoning, and a deterministic anti-hallucination rule-based fallback.
"""

import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.hardware import HardwareDetector, detector
from app.schemas import (
    ChatMessageResponse,
    CpuInfo,
    GpuInfo,
    MemoryInfo,
    MotherboardInfo,
    OsInfo,
    RamUpgradeInfo,
    StorageInfo,
)

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT", "4.0"))


class SessionContext:
    """Maintains conversational context across turns for a session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.last_category: Optional[str] = None
        self.last_question: Optional[str] = None
        self.last_answer: Optional[str] = None
        self.history: List[Dict[str, str]] = []

    def add_turn(self, question: str, answer: str, category: str):
        self.last_question = question
        self.last_answer = answer
        self.last_category = category
        self.history.append({"user": question, "assistant": answer, "category": category})
        # Keep recent 10 turns
        if len(self.history) > 10:
            self.history.pop(0)


# In-memory session store
SESSIONS: Dict[str, SessionContext] = {}


def get_or_create_session(session_id: Optional[str] = None) -> SessionContext:
    if not session_id or session_id not in SESSIONS:
        new_id = session_id or str(uuid.uuid4())
        SESSIONS[new_id] = SessionContext(new_id)
        return SESSIONS[new_id]
    return SESSIONS[session_id]


def clear_session(session_id: str) -> bool:
    if session_id in SESSIONS:
        del SESSIONS[session_id]
        return True
    return False


class IntentRouter:
    """
    Intelligent question classifier and intent router.
    Resolves hardware categories and handles multi-turn pronoun/follow-up resolution.
    """

    # Keyword and regex patterns for each hardware domain
    PATTERNS = {
        "ram_upgrade": [
            r"\b(upgrade|expand|add|more)\b.*\b(ram|memory)\b",
            r"\b(ram|memory)\b.*\b(upgrade|expand|slot|slots|max|maximum)\b",
            r"\b(how many|empty|available)\b.*\b(slots|ram slots)\b",
            r"\bcan i upgrade\b",
            r"\bis ram upgradeable\b",
        ],
        "memory": [
            r"\b(ram|memory|swap)\b",
            r"\bhow much ram\b",
            r"\bhow much memory\b",
            r"\bmemory usage\b",
            r"\bavailable ram\b",
            r"\bfree ram\b",
            r"\bused ram\b",
        ],
        "cpu": [
            r"\b(cpu|processor|cores?|threads?|frequency|ghz|mhz|intel|amd ryzen|lscpu|clock speed)\b",
            r"\bhow fast is my (laptop|pc|computer|cpu)\b",
        ],
        "storage": [
            r"\b(ssd|hdd|hard drive|disk|nvme|sata|storage|drive space|capacity|partitions?)\b",
            r"\bhow much (space|storage|disk space)\b",
            r"\bis my ssd nvme\b",
        ],
        "gpu": [
            r"\b(gpu|graphics|graphics card|video card|vram|nvidia|rtx|gtx|radeon|intel graphics)\b",
            r"\bwhat gpu\b",
        ],
        "motherboard": [
            r"\b(motherboard|mainboard|baseboard|mobo|bios|chipset)\b",
        ],
        "os": [
            r"\b(os|operating system|distro|distribution|linux|ubuntu|fedora|debian|arch|kernel|uptime)\b",
            r"\bwhat linux\b",
        ],
        "all_hardware": [
            r"\b(all|everything|complete|full specs|specs|specifications|hardware details|system info|system details)\b",
        ],
    }

    # Follow-up indicators referencing the previous conversation topic
    FOLLOW_UP_INDICATORS = [
        r"^how much is (currently )?(available|free|used)\??$",
        r"^what about (it|that)\??$",
        r"^can i upgrade (it|this)\??$",
        r"^how many cores does it have\??$",
        r"^what is its capacity\??$",
        r"^how fast is it\??$",
        r"^is it fast\??$",
    ]

    @classmethod
    def classify_intent(cls, question: str, session: Optional[SessionContext] = None) -> str:
        """
        Determines the relevant hardware domain from the natural language question,
        taking conversation history into account.
        """
        q = question.strip().lower()

        # 1. Check for explicit follow-up phrases that bind to previous topic
        if session and session.last_category:
            for pat in cls.FOLLOW_UP_INDICATORS:
                if re.search(pat, q):
                    # Check if asking about upgrade for memory
                    if "upgrade" in q:
                        return "ram_upgrade" if session.last_category in ("memory", "ram_upgrade") else session.last_category
                    return session.last_category

        # 2. Check for "What about my X?" or "And my X?" transitions
        transition_match = re.search(r"\b(what about|and my|how about)\s+(the\s+)?([a-z0-9_\s]+)", q)
        if transition_match:
            sub = transition_match.group(3).strip()
            if any(k in sub for k in ["gpu", "graphics", "video"]):
                return "gpu"
            if any(k in sub for k in ["cpu", "processor", "cores"]):
                return "cpu"
            if any(k in sub for k in ["ram", "memory"]):
                return "memory"
            if any(k in sub for k in ["disk", "storage", "ssd", "hdd"]):
                return "storage"
            if any(k in sub for k in ["motherboard", "bios", "board"]):
                return "motherboard"
            if any(k in sub for k in ["os", "linux", "distro", "kernel"]):
                return "os"

        # 3. Match specific hardware categories (Order matters: ram_upgrade before memory)
        for cat in ["all_hardware", "ram_upgrade", "storage", "gpu", "cpu", "motherboard", "os", "memory"]:
            for pat in cls.PATTERNS[cat]:
                if re.search(pat, q):
                    return cat

        # 4. If query is vague and a previous category was active, carry forward
        if session and session.last_category:
            if any(w in q for w in ["it", "this", "that", "available", "free", "used", "slots", "cores"]):
                return session.last_category

        # Default fallback is all_hardware summary
        return "all_hardware"


class RuleBasedSynthesizer:
    """
    Deterministic Natural Language Response Generator.
    Guarantees strict factual accuracy and zero hallucinations when Ollama is offline.
    """

    @staticmethod
    def answer_cpu(cpu: CpuInfo, question: str) -> str:
        q = question.lower()
        if "core" in q or "thread" in q:
            cores = cpu.physical_cores or "unknown number of"
            threads = cpu.logical_threads or "unknown number of"
            return f"Your CPU has {cores} physical core(s) and {threads} logical execution thread(s)."
        
        if "frequency" in q or "fast" in q or "speed" in q or "mhz" in q or "ghz" in q:
            mhz_info = f"current speed of {cpu.current_mhz} MHz" if cpu.current_mhz else ""
            max_info = f" (max boost: {cpu.max_mhz} MHz)" if cpu.max_mhz else ""
            if mhz_info:
                return f"Your processor ({cpu.model}) is currently running at {mhz_info}{max_info}."
            return f"Your processor model is {cpu.model}. Detailed clock speed frequencies are currently managed by the governor."

        cache_parts = []
        if cpu.l3_cache:
            cache_parts.append(f"L3 Cache: {cpu.l3_cache}")
        cache_str = f" with {', '.join(cache_parts)}" if cache_parts else ""

        cores_str = f"{cpu.physical_cores} cores / {cpu.logical_threads} threads" if cpu.physical_cores else f"{cpu.logical_threads} threads"
        return f"Your processor is {cpu.model} ({cpu.architecture}) featuring {cores_str}{cache_str}."

    @staticmethod
    def answer_memory(mem: MemoryInfo, question: str) -> str:
        q = question.lower()
        if "available" in q or "free" in q:
            pct_avail = round(100.0 - mem.percent_used, 1)
            return (
                f"Approximately {mem.available_formatted} of RAM ({pct_avail}% of total) "
                f"is currently available for new processes."
            )
        
        if "used" in q or "usage" in q:
            return (
                f"Currently, {mem.used_formatted} of RAM is in use ({mem.percent_used}% of {mem.total_formatted})."
            )
        
        if "swap" in q:
            return f"Your system has {mem.swap_total_formatted} of swap configured, with {mem.swap_used_formatted} currently used."

        return (
            f"Your laptop has {mem.total_formatted} of installed RAM. "
            f"Currently {mem.available_formatted} is available and {mem.used_formatted} is used ({mem.percent_used}%)."
        )

    @staticmethod
    def answer_storage(storage: StorageInfo, question: str) -> str:
        q = question.lower()
        if not storage.devices:
            return "No storage block devices could be detected or permission was denied."

        # Specific NVMe check
        if "nvme" in q:
            nvmes = [d for d in storage.devices if d.is_nvme and d.device_type == "disk"]
            if nvmes:
                names = ", ".join(f"{d.name} ({d.model}, {d.size_formatted})" for d in nvmes)
                return f"Yes, your system uses NVMe SSD storage! Detected NVMe drive(s): {names}."
            else:
                satadrives = [d for d in storage.devices if d.device_type == "disk"]
                sata_names = ", ".join(f"{d.name} ({d.size_formatted})" for d in satadrives)
                return f"No NVMe drives were detected. Your system is using SATA/standard drive(s): {sata_names or 'standard disk'}."

        # Specific Capacity check
        if "capacity" in q or "how much" in q or "space" in q:
            drives = [d for d in storage.devices if d.device_type == "disk"]
            breakdown = ", ".join(f"{d.name}: {d.size_formatted} ({'NVMe SSD' if d.is_nvme else 'SATA Drive'})" for d in drives)
            return f"Your laptop has a total physical storage capacity of {storage.total_capacity_formatted}. Drive breakdown: {breakdown}."

        # General drive summary
        drives = [d for d in storage.devices if d.device_type == "disk"]
        drive_strs = []
        for d in drives:
            tech = "NVMe SSD" if d.is_nvme else ("SATA SSD" if d.is_ssd else "HDD")
            drive_strs.append(f"{d.name} ({d.model}, {d.size_formatted}, {tech})")

        return f"Your laptop has {len(drives)} physical drive(s) totaling {storage.total_capacity_formatted}: {'; '.join(drive_strs)}."

    @staticmethod
    def answer_gpu(gpu: GpuInfo, question: str) -> str:
        if not gpu.devices or gpu.count == 0:
            return "No dedicated or integrated graphics adapter was recognized via PCI inspection."

        gpu_descriptions = []
        for g in gpu.devices:
            vram = f" with {g.vram_formatted} VRAM" if g.vram_formatted else ""
            temp = f" [Temp: {g.temperature}]" if g.temperature else ""
            driver = f" (Driver: {g.driver_version})" if g.driver_version else ""
            gpu_descriptions.append(f"{g.name}{vram}{driver}{temp}")

        if len(gpu_descriptions) == 1:
            return f"Your laptop has {gpu_descriptions[0]}."
        return f"Your laptop is equipped with {len(gpu_descriptions)} graphics adapters: " + " | ".join(gpu_descriptions)

    @staticmethod
    def answer_motherboard(mb: MotherboardInfo, question: str) -> str:
        bios_info = f" running BIOS {mb.bios_version} (Vendor: {mb.bios_vendor})" if mb.bios_version else ""
        return (
            f"Your motherboard is manufactured by {mb.manufacturer}, model: {mb.product_name}"
            f"{f' (Version {mb.version})' if mb.version else ''}{bios_info}."
        )

    @staticmethod
    def answer_os(os_info: OsInfo, question: str) -> str:
        uptime = f", system uptime: {os_info.uptime_formatted}" if os_info.uptime_formatted else ""
        return (
            f"You are running {os_info.distro_name} {os_info.distro_version} on architecture {os_info.architecture} "
            f"(Kernel: {os_info.kernel_version}{uptime})."
        )

    @staticmethod
    def answer_ram_upgrade(upgrade: RamUpgradeInfo, question: str) -> str:
        return f"{upgrade.assessment_summary}\n\nRecommendation: {upgrade.recommendation}"

    @staticmethod
    def answer_all(all_hw: Dict[str, Any]) -> str:
        cpu = all_hw["cpu"]
        mem = all_hw["memory"]
        storage = all_hw["storage"]
        gpu = all_hw["gpu"]
        os_info = all_hw["os"]
        upgrade = all_hw["ram_upgrade"]

        gpus_str = ", ".join(d["name"] for d in gpu.get("devices", [])) or "Host Graphics"

        return (
            f"### Complete Hardware Specifications\n"
            f"- **Operating System**: {os_info.get('distro_name')} {os_info.get('distro_version')} (Kernel: {os_info.get('kernel_version')})\n"
            f"- **Processor**: {cpu.get('model')} ({cpu.get('physical_cores')} cores, {cpu.get('logical_threads')} threads)\n"
            f"- **RAM**: {mem.get('total_formatted')} installed ({mem.get('available_formatted')} available, {mem.get('percent_used')}% used)\n"
            f"- **Storage**: {storage.get('total_capacity_formatted')} total ({storage.get('nvme_count')} NVMe drive(s))\n"
            f"- **Graphics**: {gpus_str}\n"
            f"- **RAM Upgradeability**: {upgrade.get('assessment_summary')}"
        )


class OllamaClient:
    """Handles communication with optional local Ollama LLM server."""

    @staticmethod
    async def is_available() -> bool:
        """Checks if Ollama service is running locally."""
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                res = await client.get(f"{OLLAMA_HOST}/api/tags")
                return res.status_code == 200
        except Exception:
            return False

    @staticmethod
    async def generate_response(
        question: str,
        category: str,
        hardware_json: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
    ) -> Optional[str]:
        """
        Submits strictly bounded hardware JSON and conversation context to Ollama.
        Enforces anti-hallucination constraints.
        """
        system_prompt = (
            "You are a specialized Linux Laptop Hardware Q&A Assistant.\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Base your answer SOLELY on the verified hardware telemetry JSON provided below.\n"
            "2. NEVER invent, guess, or extrapolate hardware specs. If data is not present in the JSON, "
            "say 'Data unavailable' or explain that root permission is required.\n"
            "3. Provide concise, friendly, plain English answers suitable for a laptop user.\n"
            "4. For follow-up questions, refer to the recent conversation history.\n\n"
            f"VERIFIED SYSTEM HARDWARE TELEMETRY:\n{json.dumps(hardware_json, indent=2)}"
        )

        prompt = f"User Question: {question}\nAssistant Answer:"

        payload = {
            "model": OLLAMA_MODEL,
            "system": system_prompt,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,  # Low temperature for strict determinism
                "num_predict": 256,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SECONDS) as client:
                resp = await client.post(f"{OLLAMA_HOST}/api/generate", json=payload)
                if resp.status_code == 200:
                    ans = resp.json().get("response", "").strip()
                    if ans:
                        return ans
        except Exception as exc:
            logger.debug("Ollama generation failed or timed out: %s", exc)

        return None


class AssistantCoordinator:
    """
    Main Assistant orchestrator.
    Gathers category telemetry on-demand, generates answers via Ollama or rule-based fallback,
    and returns rich structured responses.
    """

    def __init__(self, hw_detector: HardwareDetector = detector):
        self.detector = hw_detector

    def get_suggested_questions(self, current_category: str) -> List[str]:
        suggestions_map = {
            "memory": [
                "How much RAM is currently available?",
                "Can I upgrade my RAM?",
                "What GPU does my laptop have?",
            ],
            "ram_upgrade": [
                "How much RAM do I have?",
                "What is my motherboard model?",
                "Is my SSD NVMe or SATA?",
            ],
            "cpu": [
                "How many CPU cores do I have?",
                "What GPU does my laptop have?",
                "What Linux operating system am I running?",
            ],
            "storage": [
                "Is my SSD NVMe or SATA?",
                "What is my disk capacity?",
                "How much RAM do I have?",
            ],
            "gpu": [
                "What processor am I using?",
                "Tell me about my RAM.",
                "Is my SSD NVMe?",
            ],
            "motherboard": [
                "Can I upgrade my RAM?",
                "What processor model do I have?",
                "What Linux distro is running?",
            ],
            "os": [
                "Tell me about my CPU.",
                "How much RAM do I have?",
                "Show my complete hardware details.",
            ],
            "all_hardware": [
                "Is my SSD NVMe or SATA?",
                "Can I upgrade my RAM?",
                "How much RAM is currently available?",
            ],
        }
        return suggestions_map.get(
            current_category,
            ["How much RAM do I have?", "Is my SSD NVMe?", "Can I upgrade my RAM?"],
        )

    async def answer_question(
        self, question: str, session_id: Optional[str] = None
    ) -> ChatMessageResponse:
        session = get_or_create_session(session_id)
        
        # 1. Classify intent & resolve follow-up context
        category = IntentRouter.classify_intent(question, session)
        
        # 2. Query hardware information specifically required for this category
        data: Dict[str, Any] = {}
        if category == "cpu":
            info = self.detector.get_cpu_info()
            data = info.model_dump()
            fallback_answer = RuleBasedSynthesizer.answer_cpu(info, question)
        elif category == "memory":
            info = self.detector.get_memory_info()
            data = info.model_dump()
            fallback_answer = RuleBasedSynthesizer.answer_memory(info, question)
        elif category == "storage":
            info = self.detector.get_storage_info()
            data = info.model_dump()
            fallback_answer = RuleBasedSynthesizer.answer_storage(info, question)
        elif category == "gpu":
            info = self.detector.get_gpu_info()
            data = info.model_dump()
            fallback_answer = RuleBasedSynthesizer.answer_gpu(info, question)
        elif category == "motherboard":
            info = self.detector.get_motherboard_info()
            data = info.model_dump()
            fallback_answer = RuleBasedSynthesizer.answer_motherboard(info, question)
        elif category == "os":
            info = self.detector.get_os_info()
            data = info.model_dump()
            fallback_answer = RuleBasedSynthesizer.answer_os(info, question)
        elif category == "ram_upgrade":
            info = self.detector.get_ram_upgrade_assessment()
            data = info.model_dump()
            fallback_answer = RuleBasedSynthesizer.answer_ram_upgrade(info, question)
        else:  # all_hardware
            info = self.detector.get_all_hardware_info()
            data = info.model_dump()
            fallback_answer = RuleBasedSynthesizer.answer_all(data)

        # 3. Attempt Ollama synthesis first
        answer = None
        source = "rule_based_fallback"
        
        if await OllamaClient.is_available():
            answer = await OllamaClient.generate_response(
                question=question,
                category=category,
                hardware_json=data,
                conversation_history=session.history,
            )
            if answer:
                source = "ollama"

        # If Ollama is offline or unavailable, use our deterministic rule-based answer
        if not answer:
            answer = fallback_answer

        # 4. Update session context
        session.add_turn(question, answer, category)

        # 5. Build suggested follow-ups
        suggested = self.get_suggested_questions(category)

        return ChatMessageResponse(
            answer=answer,
            category=category,
            data=data,
            source=source,
            session_id=session.session_id,
            suggested_questions=suggested,
        )


# Global assistant coordinator
assistant = AssistantCoordinator()
