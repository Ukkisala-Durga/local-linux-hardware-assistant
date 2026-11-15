"""
Pydantic Schemas for Linux Laptop Hardware Q&A Assistant.
Provides strictly validated data contracts for hardware representations,
chat requests, and responses.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CpuInfo(BaseModel):
    model: str = Field(default="Unknown", description="Processor model name")
    vendor: str = Field(default="Unknown", description="CPU vendor ID")
    architecture: str = Field(default="Unknown", description="CPU architecture, e.g. x86_64 or aarch64")
    physical_cores: Optional[int] = Field(default=None, description="Number of physical CPU cores")
    logical_threads: Optional[int] = Field(default=None, description="Number of logical execution threads")
    max_mhz: Optional[float] = Field(default=None, description="Maximum CPU frequency in MHz")
    min_mhz: Optional[float] = Field(default=None, description="Minimum CPU frequency in MHz")
    current_mhz: Optional[float] = Field(default=None, description="Current CPU frequency in MHz")
    l1_cache: Optional[str] = Field(default=None, description="L1 cache size")
    l2_cache: Optional[str] = Field(default=None, description="L2 cache size")
    l3_cache: Optional[str] = Field(default=None, description="L3 cache size")
    virtualization: Optional[str] = Field(default=None, description="Virtualization support (VT-x / AMD-V)")
    raw_source: str = Field(default="lscpu", description="Primary inspection source")
    status: str = Field(default="ok", description="Status of inspection")


class MemorySlot(BaseModel):
    locator: str = Field(default="Slot", description="Slot designation, e.g. ChannelA-DIMM0")
    bank_locator: Optional[str] = Field(default=None, description="Bank locator")
    size: str = Field(default="Unknown", description="Module size or 'No Module Installed'")
    ram_type: Optional[str] = Field(default=None, description="Memory technology, e.g. DDR4, DDR5, LPDDR4")
    speed: Optional[str] = Field(default=None, description="Configured memory speed, e.g. 3200 MT/s")
    manufacturer: Optional[str] = Field(default=None, description="Memory manufacturer")
    part_number: Optional[str] = Field(default=None, description="Part number")
    form_factor: Optional[str] = Field(default=None, description="Form factor (SODIMM, Row of chips, etc.)")
    is_populated: bool = Field(default=False, description="Whether this slot is occupied")


class MemoryInfo(BaseModel):
    total_bytes: int = Field(default=0, description="Total system RAM in bytes")
    total_formatted: str = Field(default="0 B", description="Human-readable total RAM")
    used_bytes: int = Field(default=0, description="Used RAM in bytes")
    used_formatted: str = Field(default="0 B", description="Human-readable used RAM")
    available_bytes: int = Field(default=0, description="Available RAM in bytes")
    available_formatted: str = Field(default="0 B", description="Human-readable available RAM")
    free_bytes: int = Field(default=0, description="Free RAM in bytes")
    free_formatted: str = Field(default="0 B", description="Human-readable free RAM")
    percent_used: float = Field(default=0.0, description="Percentage of RAM used")
    swap_total_formatted: str = Field(default="0 B", description="Total swap space")
    swap_used_formatted: str = Field(default="0 B", description="Used swap space")
    total_slots: Optional[int] = Field(default=None, description="Total physical RAM slots")
    populated_slots: Optional[int] = Field(default=None, description="Number of populated slots")
    empty_slots: Optional[int] = Field(default=None, description="Number of available empty slots")
    slots: List[MemorySlot] = Field(default_factory=list, description="List of physical memory slots")
    max_capacity_formatted: Optional[str] = Field(default=None, description="Max RAM capacity supported by board")
    raw_source: str = Field(default="meminfo", description="Source of memory data")
    status: str = Field(default="ok", description="Status of inspection")


class StorageDevice(BaseModel):
    name: str = Field(..., description="Device name, e.g. nvme0n1 or sda")
    size_bytes: int = Field(default=0, description="Size in bytes")
    size_formatted: str = Field(default="Unknown", description="Human readable device size")
    device_type: str = Field(default="disk", description="Device type: disk or part")
    model: Optional[str] = Field(default=None, description="Disk model / brand name")
    mountpoint: Optional[str] = Field(default=None, description="Filesystem mountpoint")
    is_rotational: bool = Field(default=False, description="True for HDD, False for SSD")
    is_ssd: bool = Field(default=True, description="True if SSD/flash storage")
    is_nvme: bool = Field(default=False, description="True if connected via NVMe")
    transport: str = Field(default="Unknown", description="Bus transport, e.g. nvme, sata, usb")
    filesystem: Optional[str] = Field(default=None, description="Filesystem type, e.g. ext4, btrfs")


class StorageInfo(BaseModel):
    devices: List[StorageDevice] = Field(default_factory=list, description="Detected storage drives")
    total_capacity_bytes: int = Field(default=0, description="Total physical disk capacity in bytes")
    total_capacity_formatted: str = Field(default="0 B", description="Formatted total disk capacity")
    nvme_count: int = Field(default=0, description="Number of NVMe drives")
    sata_count: int = Field(default=0, description="Number of SATA drives")
    raw_source: str = Field(default="lsblk", description="Source of storage data")
    status: str = Field(default="ok", description="Status of inspection")


class GpuDevice(BaseModel):
    name: str = Field(..., description="GPU display or device name")
    vendor: str = Field(default="Unknown", description="NVIDIA, AMD, Intel, or Other")
    pci_slot: Optional[str] = Field(default=None, description="PCI bus address")
    vram_formatted: Optional[str] = Field(default=None, description="VRAM capacity if detectable")
    driver_version: Optional[str] = Field(default=None, description="Driver version in use")
    temperature: Optional[str] = Field(default=None, description="Current GPU temperature if detectable")


class GpuInfo(BaseModel):
    devices: List[GpuDevice] = Field(default_factory=list, description="Detected graphics cards")
    count: int = Field(default=0, description="Number of detected GPUs")
    raw_source: str = Field(default="lspci", description="Source of GPU data")
    status: str = Field(default="ok", description="Status of inspection")


class MotherboardInfo(BaseModel):
    manufacturer: str = Field(default="Unknown", description="Motherboard manufacturer")
    product_name: str = Field(default="Unknown", description="Motherboard model or product name")
    version: Optional[str] = Field(default=None, description="Hardware revision")
    serial_number: Optional[str] = Field(default=None, description="Serial number (masked for privacy)")
    bios_vendor: Optional[str] = Field(default=None, description="BIOS vendor")
    bios_version: Optional[str] = Field(default=None, description="BIOS firmware version")
    bios_date: Optional[str] = Field(default=None, description="BIOS release date")
    raw_source: str = Field(default="/sys/class/dmi/id", description="Source of motherboard data")
    status: str = Field(default="ok", description="Status of inspection")


class OsInfo(BaseModel):
    distro_name: str = Field(default="Unknown", description="Operating system distribution")
    distro_version: str = Field(default="Unknown", description="Distribution version or release")
    distro_id: str = Field(default="linux", description="OS ID e.g. ubuntu, fedora, arch, debian")
    kernel_version: str = Field(default="Unknown", description="Linux kernel release version")
    architecture: str = Field(default="Unknown", description="OS architecture, e.g. x86_64")
    hostname: str = Field(default="localhost", description="System hostname")
    uptime_formatted: Optional[str] = Field(default=None, description="System uptime")
    platform_system: str = Field(default="Linux", description="Platform system name")
    raw_source: str = Field(default="/etc/os-release", description="Source of OS data")
    status: str = Field(default="ok", description="Status of inspection")


class RamUpgradeInfo(BaseModel):
    is_upgradeable: Optional[bool] = Field(default=None, description="True if upgradeable, False if soldered/maxed, None if unknown")
    current_ram: str = Field(default="Unknown", description="Currently installed RAM capacity")
    max_capacity: str = Field(default="Unknown", description="Maximum supported capacity")
    total_slots: Optional[int] = Field(default=None, description="Total physical slots detected")
    populated_slots: Optional[int] = Field(default=None, description="Populated slots count")
    empty_slots: Optional[int] = Field(default=None, description="Available empty slots count")
    form_factor: Optional[str] = Field(default=None, description="Memory form factor, e.g. SODIMM")
    assessment_summary: str = Field(..., description="High-level upgrade assessment")
    recommendation: str = Field(..., description="Concrete upgrade guidance or steps")
    confidence: str = Field(default="high", description="high, medium, or low confidence based on available telemetry")
    status: str = Field(default="ok", description="Status of evaluation")


class AllHardwareResponse(BaseModel):
    cpu: CpuInfo
    memory: MemoryInfo
    storage: StorageInfo
    gpu: GpuInfo
    motherboard: MotherboardInfo
    os: OsInfo
    ram_upgrade: RamUpgradeInfo
    timestamp: str
    host_platform: str


class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="User's natural language question")
    session_id: Optional[str] = Field(default=None, description="Session ID for multi-turn conversation tracking")


class ChatMessageResponse(BaseModel):
    answer: str = Field(..., description="Conversational answer generated for user")
    category: str = Field(..., description="Identified hardware category")
    data: Dict[str, Any] = Field(default_factory=dict, description="Structured hardware data used to answer")
    source: str = Field(default="rule_based", description="'ollama' or 'rule_based_fallback'")
    session_id: str = Field(..., description="Conversation session ID")
    suggested_questions: List[str] = Field(default_factory=list, description="Relevant follow-up suggestions")


class HealthResponse(BaseModel):
    status: str = Field(default="ok")
    platform: str
    is_linux: bool
    ollama_available: bool
    ollama_model: Optional[str] = None
    tools_detected: Dict[str, bool] = Field(default_factory=dict)
    version: str = "1.0.0"
