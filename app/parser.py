"""
Hardware Telemetry Output Parsers and Normalizers.
Transforms raw unstructured CLI outputs and Linux pseudo-filesystem files
into clean, validated, normalized Python dictionaries.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def format_bytes(size_bytes: int) -> str:
    """Formats raw byte counts into human-readable strings (e.g., 16.0 GB)."""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    val = float(size_bytes)
    idx = 0
    while val >= 1024.0 and idx < len(units) - 1:
        val /= 1024.0
        idx += 1
    return f"{val:.1f} {units[idx]}"


def parse_lscpu(stdout: str) -> Dict[str, Any]:
    """
    Parses output from the standard Linux `lscpu` command.
    Returns normalized dictionary with core counts, architecture, and cache.
    """
    data: Dict[str, str] = {}
    for line in stdout.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            data[key.strip()] = val.strip()

    model = data.get("Model name") or data.get("Model Name") or "Unknown Processor"
    arch = data.get("Architecture", "Unknown")
    vendor = data.get("Vendor ID", "Unknown")

    # Helper to safely parse integers
    def safe_int(k: str) -> Optional[int]:
        val = data.get(k)
        if val:
            try:
                return int(val.strip())
            except ValueError:
                pass
        return None

    # Helper to safely parse floats (e.g. MHz)
    def safe_float(k: str) -> Optional[float]:
        val = data.get(k)
        if val:
            try:
                return float(val.strip().replace(",", "."))
            except ValueError:
                pass
        return None

    logical_threads = safe_int("CPU(s)")
    cores_per_socket = safe_int("Core(s) per socket")
    sockets = safe_int("Socket(s)") or 1
    
    physical_cores = None
    if cores_per_socket:
        physical_cores = cores_per_socket * sockets
    elif logical_threads:
        physical_cores = logical_threads

    max_mhz = safe_float("CPU max MHz")
    min_mhz = safe_float("CPU min MHz")
    current_mhz = safe_float("CPU MHz")

    l1_cache = data.get("L1d cache") or data.get("L1 cache")
    l2_cache = data.get("L2 cache")
    l3_cache = data.get("L3 cache")
    virtualization = data.get("Virtualization") or data.get("Virtualization type")

    return {
        "model": model,
        "vendor": vendor,
        "architecture": arch,
        "physical_cores": physical_cores,
        "logical_threads": logical_threads,
        "max_mhz": max_mhz,
        "min_mhz": min_mhz,
        "current_mhz": current_mhz,
        "l1_cache": l1_cache,
        "l2_cache": l2_cache,
        "l3_cache": l3_cache,
        "virtualization": virtualization,
        "raw_source": "lscpu",
        "status": "ok",
    }


def parse_proc_cpuinfo(content: str) -> Dict[str, Any]:
    """
    Fallback parser for /proc/cpuinfo when lscpu is not installed.
    """
    processors = []
    current: Dict[str, str] = {}
    
    for line in content.splitlines():
        line = line.strip()
        if not line:
            if current:
                processors.append(current)
                current = {}
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            current[k.strip()] = v.strip()
    if current:
        processors.append(current)

    if not processors:
        return {
            "model": "Unknown",
            "vendor": "Unknown",
            "architecture": "Unknown",
            "physical_cores": None,
            "logical_threads": None,
            "raw_source": "/proc/cpuinfo",
            "status": "partial",
        }

    first = processors[0]
    model = first.get("model name", "Unknown Processor")
    vendor = first.get("vendor_id", "Unknown")
    logical_threads = len(processors)

    # Physical cores calculation
    cores_str = first.get("cpu cores")
    physical_cores = None
    if cores_str and cores_str.isdigit():
        physical_cores = int(cores_str)
    else:
        physical_cores = logical_threads

    mhz_str = first.get("cpu MHz")
    current_mhz = float(mhz_str) if mhz_str else None
    cache_str = first.get("cache size")

    return {
        "model": model,
        "vendor": vendor,
        "architecture": "Unknown",
        "physical_cores": physical_cores,
        "logical_threads": logical_threads,
        "max_mhz": None,
        "min_mhz": None,
        "current_mhz": current_mhz,
        "l1_cache": None,
        "l2_cache": None,
        "l3_cache": cache_str,
        "virtualization": None,
        "raw_source": "/proc/cpuinfo",
        "status": "ok",
    }


def parse_proc_meminfo(content: str) -> Dict[str, Any]:
    """
    Parses /proc/meminfo key-value pairs (in kB).
    Accurate kernel interface without needing external binaries.
    """
    mem_dict: Dict[str, int] = {}
    for line in content.splitlines():
        parts = line.split(":")
        if len(parts) == 2:
            key = parts[0].strip()
            val_str = parts[1].strip().split()[0]
            try:
                mem_dict[key] = int(val_str) * 1024  # Convert kB to bytes
            except ValueError:
                pass

    total = mem_dict.get("MemTotal", 0)
    free = mem_dict.get("MemFree", 0)
    available = mem_dict.get("MemAvailable", free)
    buffers = mem_dict.get("Buffers", 0)
    cached = mem_dict.get("Cached", 0)
    swap_total = mem_dict.get("SwapTotal", 0)
    swap_free = mem_dict.get("SwapFree", 0)
    swap_used = swap_total - swap_free

    used = total - available if total > available else (total - free - buffers - cached)
    if used < 0:
        used = 0

    pct_used = round((used / total * 100.0), 1) if total > 0 else 0.0

    return {
        "total_bytes": total,
        "total_formatted": format_bytes(total),
        "used_bytes": used,
        "used_formatted": format_bytes(used),
        "available_bytes": available,
        "available_formatted": format_bytes(available),
        "free_bytes": free,
        "free_formatted": format_bytes(free),
        "percent_used": pct_used,
        "swap_total_formatted": format_bytes(swap_total),
        "swap_used_formatted": format_bytes(swap_used),
        "raw_source": "/proc/meminfo",
        "status": "ok",
    }


def parse_free(stdout: str) -> Dict[str, Any]:
    """
    Parses stdout from `free -b` (bytes).
    """
    lines = stdout.strip().splitlines()
    if len(lines) < 2:
        return {"status": "error", "error": "Unexpected free command output"}

    # headers: line 0 (total used free shared buff/cache available)
    # Mem: line 1
    mem_parts = lines[1].split()
    if len(mem_parts) < 4:
        return {"status": "error", "error": "Incomplete memory line"}

    try:
        total = int(mem_parts[1])
        used = int(mem_parts[2])
        free = int(mem_parts[3])
        # Available may be at index 6 or last column
        available = int(mem_parts[6]) if len(mem_parts) >= 7 else free
        
        swap_total = 0
        swap_used = 0
        if len(lines) >= 3 and "Swap:" in lines[2]:
            swap_parts = lines[2].split()
            if len(swap_parts) >= 3:
                swap_total = int(swap_parts[1])
                swap_used = int(swap_parts[2])

        pct_used = round((used / total * 100.0), 1) if total > 0 else 0.0

        return {
            "total_bytes": total,
            "total_formatted": format_bytes(total),
            "used_bytes": used,
            "used_formatted": format_bytes(used),
            "available_bytes": available,
            "available_formatted": format_bytes(available),
            "free_bytes": free,
            "free_formatted": format_bytes(free),
            "percent_used": pct_used,
            "swap_total_formatted": format_bytes(swap_total),
            "swap_used_formatted": format_bytes(swap_used),
            "raw_source": "free",
            "status": "ok",
        }
    except (ValueError, IndexError) as err:
        return {"status": "error", "error": f"Failed parsing free output: {err}"}


def parse_lsblk(stdout: str) -> List[Dict[str, Any]]:
    """
    Parses JSON output from `lsblk -J -b -o NAME,SIZE,TYPE,MOUNTPOINT,MODEL,ROTA,TRAN,FSTYPE`.
    Normalizes device properties, classifying NVMe vs SATA vs SSD vs HDD.
    """
    devices: List[Dict[str, Any]] = []

    try:
        data = json.loads(stdout)
        raw_devices = data.get("blockdevices", [])
    except json.JSONDecodeError:
        logger.warning("lsblk did not return valid JSON, attempting simple table parse")
        return []

    def process_node(node: Dict[str, Any]):
        name = str(node.get("name", "")).strip()
        dev_type = str(node.get("type", "disk")).lower().strip()
        
        # Filter out loop/snap virtual devices
        if dev_type == "loop" or name.startswith("loop"):
            return

        size_raw = node.get("size")
        size_bytes = 0
        if size_raw is not None:
            try:
                size_bytes = int(size_raw)
            except (ValueError, TypeError):
                pass

        model = node.get("model")
        if model:
            model = str(model).strip()

        mountpoint = node.get("mountpoint")
        if mountpoint:
            mountpoint = str(mountpoint).strip()

        # ROTA: 1 = rotational (HDD), 0 = non-rotational (SSD/NVMe)
        rota_val = node.get("rota")
        is_rotational = True
        if rota_val in (0, "0", False, "false"):
            is_rotational = False

        tran = str(node.get("tran") or "").lower().strip()
        # Detect NVMe from tran or device naming (nvme0n1)
        is_nvme = "nvme" in tran or name.startswith("nvme")
        if is_nvme and not tran:
            tran = "nvme"
        elif not tran and ("sd" in name or "hd" in name):
            tran = "sata"

        is_ssd = (not is_rotational) or is_nvme

        device_dict = {
            "name": name,
            "size_bytes": size_bytes,
            "size_formatted": format_bytes(size_bytes),
            "device_type": dev_type,
            "model": model or "Generic Drive",
            "mountpoint": mountpoint,
            "is_rotational": is_rotational,
            "is_ssd": is_ssd,
            "is_nvme": is_nvme,
            "transport": tran or "unknown",
            "filesystem": node.get("fstype"),
        }
        devices.append(device_dict)

        # Recurse children (partitions)
        for child in node.get("children", []):
            process_node(child)

    for item in raw_devices:
        process_node(item)

    return devices


def parse_lspci(stdout: str) -> List[Dict[str, Any]]:
    """
    Parses `lspci` output to identify graphics display adapters (VGA, 3D, Display).
    Extracts GPU vendor (NVIDIA, AMD, Intel) and device description.
    """
    gpus: List[Dict[str, Any]] = []
    
    for line in stdout.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue
        
        # Check for graphics controller classes
        lower = line_clean.lower()
        if any(cls in lower for cls in ["vga compatible controller", "3d controller", "display controller"]):
            # Line format typically: 01:00.0 VGA compatible controller: NVIDIA Corporation GA106M [GeForce RTX 3060 Mobile] (rev a1)
            parts = line_clean.split(":", 2)
            pci_slot = parts[0].strip() if len(parts) >= 1 else None
            
            desc = parts[2].strip() if len(parts) >= 3 else line_clean
            
            # Determine vendor with word boundaries to avoid false positives (e.g. 'ati' in 'compatible')
            vendor = "Other"
            if re.search(r"\bnvidia\b", lower):
                vendor = "NVIDIA"
            elif re.search(r"\b(amd|ati|radeon|advanced micro devices)\b", lower):
                vendor = "AMD"
            elif re.search(r"\bintel\b", lower):
                vendor = "Intel"

            gpus.append({
                "name": desc,
                "vendor": vendor,
                "pci_slot": pci_slot,
                "vram_formatted": None,
                "driver_version": None,
                "temperature": None,
            })

    return gpus


def parse_nvidia_smi(stdout: str) -> List[Dict[str, Any]]:
    """
    Parses output from `nvidia-smi --query-gpu=... --format=csv,noheader,nounits`
    """
    gpus: List[Dict[str, Any]] = []
    for line in stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            name = parts[0]
            try:
                vram_mb = int(parts[1])
                vram_formatted = f"{vram_mb / 1024.0:.1f} GB" if vram_mb >= 1024 else f"{vram_mb} MB"
            except ValueError:
                vram_formatted = f"{parts[1]} MB"

            driver = parts[3] if len(parts) >= 4 else None
            temp = f"{parts[4]} °C" if len(parts) >= 5 and parts[4].isdigit() else None

            gpus.append({
                "name": name,
                "vendor": "NVIDIA",
                "pci_slot": None,
                "vram_formatted": vram_formatted,
                "driver_version": driver,
                "temperature": temp,
            })
    return gpus


def parse_dmidecode_memory(stdout: str) -> Dict[str, Any]:
    """
    Parses output of `dmidecode -t memory`.
    Extracts physical memory array maximum capacity, total slots, populated slots,
    and individual module attributes (SODIMM, DDR type, speed, size).
    """
    max_cap_match = re.search(r"Maximum Capacity:\s*([^\n\r]+)", stdout, re.IGNORECASE)
    max_capacity = max_cap_match.group(1).strip() if max_cap_match else "Unknown"

    slots_match = re.search(r"Number Of Devices:\s*(\d+)", stdout, re.IGNORECASE)
    total_slots_reported = int(slots_match.group(1)) if slots_match else None

    # Parse individual Memory Device blocks
    blocks = re.split(r"Handle 0x[0-9a-fA-F]+,\s+DMI type 17,", stdout)
    
    slots: List[Dict[str, Any]] = []
    for block in blocks[1:]:  # skip preamble
        size_m = re.search(r"Size:\s*([^\n\r]+)", block)
        type_m = re.search(r"Type:\s*([^\n\r]+)", block)
        speed_m = re.search(r"Speed:\s*([^\n\r]+)", block)
        mfr_m = re.search(r"Manufacturer:\s*([^\n\r]+)", block)
        part_m = re.search(r"Part Number:\s*([^\n\r]+)", block)
        loc_m = re.search(r"Locator:\s*([^\n\r]+)", block)
        bank_m = re.search(r"Bank Locator:\s*([^\n\r]+)", block)
        form_m = re.search(r"Form Factor:\s*([^\n\r]+)", block)

        size_str = size_m.group(1).strip() if size_m else "Unknown"
        is_populated = bool(
            size_str
            and "no module" not in size_str.lower()
            and "installed" not in size_str.lower()
            and size_str.lower() != "unknown"
            and not size_str.startswith("0")
        )

        slot_item = {
            "locator": loc_m.group(1).strip() if loc_m else f"Slot {len(slots)+1}",
            "bank_locator": bank_m.group(1).strip() if bank_m else None,
            "size": size_str,
            "ram_type": type_m.group(1).strip() if type_m else None,
            "speed": speed_m.group(1).strip() if speed_m else None,
            "manufacturer": mfr_m.group(1).strip() if mfr_m else None,
            "part_number": part_m.group(1).strip() if part_m else None,
            "form_factor": form_m.group(1).strip() if form_m else None,
            "is_populated": is_populated,
        }
        slots.append(slot_item)

    total_slots = total_slots_reported if total_slots_reported is not None else len(slots)
    populated = sum(1 for s in slots if s["is_populated"])
    empty = max(0, total_slots - populated)

    return {
        "max_capacity": max_capacity,
        "total_slots": total_slots,
        "populated_slots": populated,
        "empty_slots": empty,
        "slots": slots,
        "raw_source": "dmidecode",
        "status": "ok",
    }


def parse_dmidecode_baseboard(stdout: str) -> Dict[str, Any]:
    """
    Parses output of `dmidecode -t baseboard`.
    """
    mfr_match = re.search(r"Manufacturer:\s*([^\n\r]+)", stdout)
    product_match = re.search(r"Product Name:\s*([^\n\r]+)", stdout)
    version_match = re.search(r"Version:\s*([^\n\r]+)", stdout)
    serial_match = re.search(r"Serial Number:\s*([^\n\r]+)", stdout)

    serial = serial_match.group(1).strip() if serial_match else None
    # Mask serial number for privacy
    if serial and len(serial) > 4:
        serial = serial[:2] + ("*" * (len(serial) - 4)) + serial[-2:]

    return {
        "manufacturer": mfr_match.group(1).strip() if mfr_match else "Unknown",
        "product_name": product_match.group(1).strip() if product_match else "Unknown",
        "version": version_match.group(1).strip() if version_match else None,
        "serial_number": serial,
        "raw_source": "dmidecode",
        "status": "ok",
    }


def parse_os_release(content: str) -> Dict[str, Any]:
    """
    Parses /etc/os-release standard format.
    """
    res: Dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            res[k.strip()] = v

    name = res.get("PRETTY_NAME") or res.get("NAME") or "Linux"
    version = res.get("VERSION") or res.get("VERSION_ID") or ""
    os_id = res.get("ID", "linux").lower()

    return {
        "distro_name": name,
        "distro_version": version,
        "distro_id": os_id,
        "raw_source": "/etc/os-release",
        "status": "ok",
    }


def parse_uname(stdout: str) -> Dict[str, Any]:
    """
    Parses `uname -a` or parts.
    Example: Linux laptop-ubuntu 6.5.0-35-generic #35~22.04.1-Ubuntu SMP PREEMPT_DYNAMIC x86_64
    """
    parts = stdout.strip().split()
    if len(parts) >= 3:
        kernel = parts[2]
        arch = parts[-1] if len(parts) >= 5 else "Unknown"
        hostname = parts[1] if len(parts) >= 2 else "localhost"
        return {
            "kernel_version": kernel,
            "architecture": arch,
            "hostname": hostname,
        }
    return {
        "kernel_version": stdout.strip() or "Unknown",
        "architecture": "Unknown",
        "hostname": "localhost",
    }
