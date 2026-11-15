"""
FastAPI Application Entrypoint for Linux Laptop Hardware Q&A Assistant.
Exposes RESTful endpoints for hardware telemetry, live chat, health checks,
and serves the web interface.
"""

import logging
import os
import platform
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.assistant import (
    OLLAMA_MODEL,
    OllamaClient,
    assistant,
    clear_session,
)
from app.commands import discover_available_tools
from app.hardware import detector
from app.schemas import (
    AllHardwareResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    CpuInfo,
    GpuInfo,
    HealthResponse,
    MemoryInfo,
    MotherboardInfo,
    OsInfo,
    RamUpgradeInfo,
    StorageInfo,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("linux_hardware_assistant")

app = FastAPI(
    title="Linux Laptop Hardware Q&A Assistant",
    description="Intelligent local hardware telemetry and natural-language Q&A assistant for Linux laptops.",
    version="1.0.0",
)

# Enable CORS for local client interactions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Resolve project paths
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Mount static asset directory
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serves the responsive chatbot web dashboard."""
    index_path = TEMPLATES_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Index template not found.")
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@app.get("/api/health", response_model=HealthResponse)
async def get_health():
    """Returns application health, OS platform details, tool discovery, and Ollama status."""
    ollama_ok = await OllamaClient.is_available()
    tools = discover_available_tools()
    
    return HealthResponse(
        status="healthy",
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
        is_linux=(platform.system().lower() == "linux"),
        ollama_available=ollama_ok,
        ollama_model=OLLAMA_MODEL if ollama_ok else None,
        tools_detected=tools,
        version="1.0.0",
    )


@app.get("/api/hardware", response_model=AllHardwareResponse)
async def get_all_hardware():
    """Returns comprehensive detected hardware telemetry across all subsystems."""
    try:
        return detector.get_all_hardware_info()
    except Exception as exc:
        logger.exception("Failed gathering complete hardware details")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/hardware/cpu", response_model=CpuInfo)
async def get_cpu():
    """Returns CPU specifications (model, cores, threads, clock speeds, cache)."""
    try:
        return detector.get_cpu_info()
    except Exception as exc:
        logger.exception("Failed gathering CPU details")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/hardware/memory", response_model=MemoryInfo)
async def get_memory():
    """Returns RAM telemetry (total, used, available, swap, physical slots)."""
    try:
        return detector.get_memory_info()
    except Exception as exc:
        logger.exception("Failed gathering Memory details")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/hardware/storage", response_model=StorageInfo)
async def get_storage():
    """Returns storage drive telemetry (NVMe vs SATA, SSD vs HDD, partition sizes)."""
    try:
        return detector.get_storage_info()
    except Exception as exc:
        logger.exception("Failed gathering Storage details")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/hardware/gpu", response_model=GpuInfo)
async def get_gpu():
    """Returns GPU information (NVIDIA, AMD, Intel, display adapters)."""
    try:
        return detector.get_gpu_info()
    except Exception as exc:
        logger.exception("Failed gathering GPU details")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/hardware/motherboard", response_model=MotherboardInfo)
async def get_motherboard():
    """Returns motherboard and BIOS telemetry."""
    try:
        return detector.get_motherboard_info()
    except Exception as exc:
        logger.exception("Failed gathering Motherboard details")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/hardware/os", response_model=OsInfo)
async def get_os():
    """Returns Linux distribution, kernel release, and uptime information."""
    try:
        return detector.get_os_info()
    except Exception as exc:
        logger.exception("Failed gathering OS details")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/hardware/ram-upgrade", response_model=RamUpgradeInfo)
async def get_ram_upgrade():
    """Evaluates whether laptop RAM can be expanded, returning slot topology and maximum capacity."""
    try:
        return detector.get_ram_upgrade_assessment()
    except Exception as exc:
        logger.exception("Failed evaluating RAM upgradeability")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/chat", response_model=ChatMessageResponse)
async def chat(request: ChatMessageRequest):
    """
    Accepts natural-language hardware queries, invokes precise system inspection tools,
    maintains conversation history, and returns an accurate answer.
    """
    try:
        response = await assistant.answer_question(
            question=request.message,
            session_id=request.session_id,
        )
        return response
    except Exception as exc:
        logger.exception("Error processing chat message")
        raise HTTPException(status_code=500, detail=f"Assistant processing error: {str(exc)}")


@app.post("/api/chat/clear")
async def clear_chat_session(payload: Dict[str, str]):
    """Clears the conversational context for a given session ID."""
    session_id = payload.get("session_id")
    if session_id:
        cleared = clear_session(session_id)
        return {"status": "cleared" if cleared else "not_found", "session_id": session_id}
    return {"status": "ignored", "error": "Missing session_id"}
