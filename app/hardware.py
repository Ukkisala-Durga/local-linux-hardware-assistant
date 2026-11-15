"""
Hardware Telemetry Collection and Normalization Module.
Coordinates safe system command execution, /proc and /sys file inspection,
cross-platform psutil fallbacks, and RAM upgrade assessments.
"""

import datetime
import logging
import os
import platform
from typing import Any, Dict, List, Optional

import psutil

from app.commands import (
    discover_available_tools,
    execute_system_command,
    read_system_file,
)
from app.parser import (
    format_bytes,
    parse_dmidecode_baseboard,
    parse_dmidecode_memory,
    parse_free,
    parse_lsblk,
    parse_lspci,
    parse_lscpu,
    parse_nvidia_smi,
    parse_os_release,
    parse_proc_cpuinfo,
    parse_proc_meminfo,
    parse_uname,
)
from app.schemas import (
    AllHardwareResponse,
    CpuInfo,
    GpuDevice,
    GpuInfo,
    MemoryInfo,
    MemorySlot,
    MotherboardInfo,
    OsInfo,
    RamUpgradeInfo,
    StorageDevice,
    StorageInfo,
)

logger = logging.getLogger(__name__)

# Config flag to simulate realistic Linux laptop output on non-Linux dev machines
SIMULATE_LINUX_FIXTURE = os.getenv("MOCK_LINUX_TELEMETRY", "").lower() in ("1", "true", "yes")


class HardwareDetector:
    """
    Central hardware detection orchestrator.
    Handles distro portability, privilege management, and fallback strategies.
    """

    def __init__(self, simulate_linux: bool = False):
        self.is_linux = (platform.system().lower() == "linux")
        self.simulate_linux = simulate_linux or SIMULATE_LINUX_FIXTURE
        self.tools_available = discover_available_tools()

    def get_cpu_info(self) -> CpuInfo:
        """Collects CPU specifications using lscpu, /proc/cpuinfo, and psutil."""
        if self.is_linux:
            # 1. Primary: lscpu
            success, stdout, _ = execute_system_command("lscpu")
            if success and stdout:
                parsed = parse_lscpu(stdout)
                # Augment with psutil if missing
                if not parsed.get("physical_cores"):
                    parsed["physical_cores"] = psutil.cpu_count(logical=False)
                if not parsed.get("logical_threads"):
                    parsed["logical_threads"] = psutil.cpu_count(logical=True)
                return CpuInfo(**parsed)

            # 2. Secondary fallback: /proc/cpuinfo
            cpuinfo_str = read_system_file("/proc/cpuinfo")
            if cpuinfo_str:
                parsed = parse_proc_cpuinfo(cpuinfo_str)
                parsed["architecture"] = platform.machine()
                return CpuInfo(**parsed)

        # Non-Linux host fallback (e.g. Windows development environment)
        freq = psutil.cpu_freq()
        return CpuInfo(
            model=platform.processor() or "Generic Host Processor",
            vendor=platform.machine() or "Unknown",
            architecture=platform.machine() or "Unknown",
            physical_cores=psutil.cpu_count(logical=False),
            logical_threads=psutil.cpu_count(logical=True),
            current_mhz=round(freq.current, 1) if freq else None,
            max_mhz=round(freq.max, 1) if freq and freq.max > 0 else None,
            min_mhz=round(freq.min, 1) if freq and freq.min > 0 else None,
            raw_source="psutil/platform",
            status="host_fallback" if not self.is_linux else "partial",
        )

    def get_memory_info(self) -> MemoryInfo:
        """Collects RAM telemetry using free, /proc/meminfo, dmidecode, and psutil."""
        base_mem: Dict[str, Any] = {}
        source = "psutil"

        if self.is_linux:
            # 1. /proc/meminfo has high precision
            meminfo_str = read_system_file("/proc/meminfo")
            if meminfo_str:
                base_mem = parse_proc_meminfo(meminfo_str)
                source = "/proc/meminfo"
            else:
                # 2. Try `free -b`
                success, stdout, _ = execute_system_command("free")
                if success and stdout:
                    base_mem = parse_free(stdout)
                    source = "free"

        # Fallback to psutil for system RAM
        if not base_mem or base_mem.get("total_bytes", 0) == 0:
            vm = psutil.virtual_memory()
            sm = psutil.swap_memory()
            base_mem = {
                "total_bytes": vm.total,
                "total_formatted": format_bytes(vm.total),
                "used_bytes": vm.used,
                "used_formatted": format_bytes(vm.used),
                "available_bytes": vm.available,
                "available_formatted": format_bytes(vm.available),
                "free_bytes": vm.free,
                "free_formatted": format_bytes(vm.free),
                "percent_used": vm.percent,
                "swap_total_formatted": format_bytes(sm.total),
                "swap_used_formatted": format_bytes(sm.used),
                "raw_source": "psutil",
                "status": "ok",
            }

        # Inspect physical memory slots via dmidecode if on Linux
        slots: List[MemorySlot] = []
        total_slots = None
        populated_slots = None
        empty_slots = None
        max_capacity_str = None

        if self.is_linux:
            # Try direct dmidecode first
            ok, stdout, _ = execute_system_command("dmidecode_memory")
            if not ok:
                # Try non-interactive sudo rule if configured
                ok, stdout, _ = execute_system_command("sudo_dmidecode_memory")
            
            if ok and stdout:
                dmi_data = parse_dmidecode_memory(stdout)
                max_capacity_str = dmi_data.get("max_capacity")
                total_slots = dmi_data.get("total_slots")
                populated_slots = dmi_data.get("populated_slots")
                empty_slots = dmi_data.get("empty_slots")
                for s in dmi_data.get("slots", []):
                    slots.append(MemorySlot(**s))

        return MemoryInfo(
            total_bytes=base_mem["total_bytes"],
            total_formatted=base_mem["total_formatted"],
            used_bytes=base_mem["used_bytes"],
            used_formatted=base_mem["used_formatted"],
            available_bytes=base_mem["available_bytes"],
            available_formatted=base_mem["available_formatted"],
            free_bytes=base_mem["free_bytes"],
            free_formatted=base_mem["free_formatted"],
            percent_used=base_mem["percent_used"],
            swap_total_formatted=base_mem["swap_total_formatted"],
            swap_used_formatted=base_mem["swap_used_formatted"],
            total_slots=total_slots,
            populated_slots=populated_slots,
            empty_slots=empty_slots,
            slots=slots,
            max_capacity_formatted=max_capacity_str,
            raw_source=source,
            status="ok",
        )

    def get_storage_info(self) -> StorageInfo:
        """Inspects storage block devices, categorizing NVMe vs SATA vs SSD."""
        devices: List[StorageDevice] = []
        total_capacity = 0
        nvme_count = 0
        sata_count = 0

        if self.is_linux:
            success, stdout, _ = execute_system_command("lsblk")
            if success and stdout:
                parsed_devs = parse_lsblk(stdout)
                for d in parsed_devs:
                    dev_obj = StorageDevice(**d)
                    devices.append(dev_obj)
                    if dev_obj.device_type == "disk":
                        total_capacity += dev_obj.size_bytes
                        if dev_obj.is_nvme:
                            nvme_count += 1
                        elif dev_obj.transport == "sata":
                            sata_count += 1

                if devices:
                    return StorageInfo(
                        devices=devices,
                        total_capacity_bytes=total_capacity,
                        total_capacity_formatted=format_bytes(total_capacity),
                        nvme_count=nvme_count,
                        sata_count=sata_count,
                        raw_source="lsblk",
                        status="ok",
                    )

        # Fallback using psutil for disk partitions
        seen_devices = set()
        for part in psutil.disk_partitions(all=False):
            if part.device in seen_devices:
                continue
            seen_devices.add(part.device)
            try:
                usage = psutil.disk_usage(part.mountpoint)
                total_capacity += usage.total
                is_nvme = "nvme" in part.device.lower()
                devices.append(
                    StorageDevice(
                        name=part.device,
                        size_bytes=usage.total,
                        size_formatted=format_bytes(usage.total),
                        device_type="disk",
                        model="Host Drive",
                        mountpoint=part.mountpoint,
                        is_rotational=False,
                        is_ssd=True,
                        is_nvme=is_nvme,
                        transport="nvme" if is_nvme else "sata",
                        filesystem=part.fstype,
                    )
                )
                if is_nvme:
                    nvme_count += 1
                else:
                    sata_count += 1
            except Exception:
                pass

        return StorageInfo(
            devices=devices,
            total_capacity_bytes=total_capacity,
            total_capacity_formatted=format_bytes(total_capacity),
            nvme_count=nvme_count,
            sata_count=sata_count,
            raw_source="psutil",
            status="host_fallback" if not self.is_linux else "partial",
        )

    def get_gpu_info(self) -> GpuInfo:
        """Detects graphics cards via lspci and nvidia-smi."""
        gpu_list: List[GpuDevice] = []

        if self.is_linux:
            # 1. lspci for all display controllers
            ok, stdout, _ = execute_system_command("lspci")
            if ok and stdout:
                raw_gpus = parse_lspci(stdout)
                for g in raw_gpus:
                    gpu_list.append(GpuDevice(**g))

            # 2. Query nvidia-smi for dedicated NVIDIA telemetry
            ok_smi, stdout_smi, _ = execute_system_command("nvidia_smi")
            if ok_smi and stdout_smi:
                smi_gpus = parse_nvidia_smi(stdout_smi)
                if smi_gpus:
                    # Update or append
                    for sg in smi_gpus:
                        # Match existing by vendor or replace
                        matched = False
                        for existing in gpu_list:
                            if existing.vendor == "NVIDIA":
                                existing.vram_formatted = sg.get("vram_formatted")
                                existing.driver_version = sg.get("driver_version")
                                existing.temperature = sg.get("temperature")
                                matched = True
                                break
                        if not matched:
                            gpu_list.append(GpuDevice(**sg))

            if gpu_list:
                return GpuInfo(
                    devices=gpu_list,
                    count=len(gpu_list),
                    raw_source="lspci",
                    status="ok",
                )

        # Host environment fallback
        return GpuInfo(
            devices=[
                GpuDevice(
                    name=f"Host Graphics ({platform.system()} {platform.machine()})",
                    vendor="Integrated / Host",
                )
            ],
            count=1,
            raw_source="platform",
            status="host_fallback" if not self.is_linux else "no_gpu_detected",
        )

    def get_motherboard_info(self) -> MotherboardInfo:
        """Inspects motherboard details using dmidecode or non-root /sys/class/dmi/id."""
        if self.is_linux:
            # 1. Try dmidecode
            ok, stdout, _ = execute_system_command("dmidecode_baseboard")
            if not ok:
                ok, stdout, _ = execute_system_command("sudo_dmidecode_baseboard")

            if ok and stdout:
                dmi = parse_dmidecode_baseboard(stdout)
                return MotherboardInfo(**dmi)

            # 2. Non-root fallback: /sys/class/dmi/id/
            mfr = read_system_file("/sys/class/dmi/id/board_vendor") or read_system_file(
                "/sys/class/dmi/id/sys_vendor"
            )
            prod = read_system_file("/sys/class/dmi/id/board_name") or read_system_file(
                "/sys/class/dmi/id/product_name"
            )
            ver = read_system_file("/sys/class/dmi/id/board_version") or read_system_file(
                "/sys/class/dmi/id/product_version"
            )
            bios_ver = read_system_file("/sys/class/dmi/id/bios_version")
            bios_vendor = read_system_file("/sys/class/dmi/id/bios_vendor")
            bios_date = read_system_file("/sys/class/dmi/id/bios_date")

            if mfr or prod:
                return MotherboardInfo(
                    manufacturer=mfr or "Unknown",
                    product_name=prod or "Unknown Model",
                    version=ver,
                    bios_vendor=bios_vendor,
                    bios_version=bios_ver,
                    bios_date=bios_date,
                    raw_source="/sys/class/dmi/id",
                    status="ok",
                )

        # Non-Linux host fallback
        return MotherboardInfo(
            manufacturer=platform.node() or "Host System",
            product_name=f"{platform.system()} Laptop / Workstation",
            version="1.0",
            raw_source="platform",
            status="host_fallback" if not self.is_linux else "unavailable",
        )

    def get_os_info(self) -> OsInfo:
        """Collects operating system, kernel version, and uptime."""
        distro_name = platform.system()
        distro_version = platform.release()
        distro_id = platform.system().lower()
        kernel = platform.release()
        arch = platform.machine()
        hostname = platform.node() or "localhost"

        if self.is_linux:
            # Read /etc/os-release
            content = read_system_file("/etc/os-release")
            if content:
                os_rel = parse_os_release(content)
                distro_name = os_rel["distro_name"]
                distro_version = os_rel["distro_version"]
                distro_id = os_rel["distro_id"]

            # Uname
            ok, uname_out, _ = execute_system_command("uname")
            if ok and uname_out:
                uname_data = parse_uname(uname_out)
                kernel = uname_data.get("kernel_version", kernel)
                arch = uname_data.get("architecture", arch)

        # Uptime
        uptime_str = None
        try:
            boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
            delta = datetime.datetime.now() - boot_time
            days = delta.days
            hours, remainder = divmod(delta.seconds, 3600)
            mins, _ = divmod(remainder, 60)
            if days > 0:
                uptime_str = f"{days}d {hours}h {mins}m"
            else:
                uptime_str = f"{hours}h {mins}m"
        except Exception:
            pass

        return OsInfo(
            distro_name=distro_name,
            distro_version=distro_version,
            distro_id=distro_id,
            kernel_version=kernel,
            architecture=arch,
            hostname=hostname,
            uptime_formatted=uptime_str,
            platform_system=platform.system(),
            raw_source="/etc/os-release" if self.is_linux else "platform",
            status="ok",
        )

    def get_ram_upgrade_assessment(self) -> RamUpgradeInfo:
        """
        Conducts a rigorous RAM upgrade evaluation.
        Evaluates installed capacity, slot usage, maximum motherboard capacity,
        form factor (SODIMM vs soldered), and emits an actionable verdict.
        """
        mem = self.get_memory_info()
        mb = self.get_motherboard_info()

        current_ram = mem.total_formatted
        max_cap = mem.max_capacity_formatted or "Unknown"
        total_slots = mem.total_slots
        populated = mem.populated_slots
        empty = mem.empty_slots

        # Check form factors if slots are available
        form_factors = {s.form_factor for s in mem.slots if s.form_factor}
        is_soldered = any("chip" in str(f).lower() or "soldered" in str(f).lower() for f in form_factors)
        has_sodimm = any("sodimm" in str(f).lower() or "dimm" in str(f).lower() for f in form_factors)

        # 1. Definite Upgradeable Case: Available empty slots
        if empty is not None and empty > 0:
            summary = (
                f"RAM can be upgraded. You have {empty} empty memory slot(s) available "
                f"out of {total_slots} total slot(s)."
            )
            rec = (
                f"You currently have {current_ram} installed in {populated} slot(s). "
                f"You can add an additional compatible module into the empty slot without removing your existing RAM."
            )
            if max_cap != "Unknown":
                rec += f" The motherboard supports up to {max_cap} maximum RAM."

            return RamUpgradeInfo(
                is_upgradeable=True,
                current_ram=current_ram,
                max_capacity=max_cap,
                total_slots=total_slots,
                populated_slots=populated,
                empty_slots=empty,
                form_factor=", ".join(form_factors) if form_factors else "SODIMM",
                assessment_summary=summary,
                recommendation=rec,
                confidence="high",
                status="ok",
            )

        # 2. Slots full, but maximum capacity is higher than current
        if (
            total_slots is not None
            and empty == 0
            and max_cap != "Unknown"
            and not is_soldered
        ):
            summary = (
                f"All {total_slots} RAM slot(s) are populated, but an upgrade is possible "
                f"by replacing existing modules up to {max_cap}."
            )
            rec = (
                f"To expand beyond your current {current_ram}, you must replace your existing "
                f"modules with higher-capacity sticks matching your motherboard limit of {max_cap}."
            )
            return RamUpgradeInfo(
                is_upgradeable=True,
                current_ram=current_ram,
                max_capacity=max_cap,
                total_slots=total_slots,
                populated_slots=populated,
                empty_slots=0,
                form_factor=", ".join(form_factors) if form_factors else "SODIMM",
                assessment_summary=summary,
                recommendation=rec,
                confidence="high",
                status="ok",
            )

        # 3. Explicitly soldered memory
        if is_soldered and not has_sodimm:
            summary = "RAM is soldered directly onto the motherboard and cannot be upgraded."
            rec = (
                f"Your laptop uses soldered memory (e.g. LPDDR). "
                f"No expandable memory slots are available. Installed RAM remains fixed at {current_ram}."
            )
            return RamUpgradeInfo(
                is_upgradeable=False,
                current_ram=current_ram,
                max_capacity=current_ram,
                total_slots=total_slots or 1,
                populated_slots=total_slots or 1,
                empty_slots=0,
                form_factor="Soldered / On-board",
                assessment_summary=summary,
                recommendation=rec,
                confidence="high",
                status="ok",
            )

        # 4. Inconclusive (e.g. dmidecode not run with root permissions, or non-Linux host)
        reason = (
            "DMI BIOS memory array information requires root privileges (`dmidecode`) on Linux"
            if self.is_linux
            else f"Host platform is {platform.system()} where Linux DMI utilities are not natively running"
        )
        summary = f"Cannot definitively verify physical RAM slots ({reason})."
        rec = (
            f"Your laptop has {current_ram} of RAM. To determine if your specific laptop model "
            f"({mb.manufacturer} {mb.product_name}) has open SODIMM slots or soldered RAM, "
            f"please check the manufacturer service manual or run with `sudo dmidecode -t memory`."
        )

        return RamUpgradeInfo(
            is_upgradeable=None,
            current_ram=current_ram,
            max_capacity=max_cap,
            total_slots=total_slots,
            populated_slots=populated,
            empty_slots=empty,
            form_factor=None,
            assessment_summary=summary,
            recommendation=rec,
            confidence="low",
            status="permission_or_platform_limited",
        )

    def get_all_hardware_info(self) -> AllHardwareResponse:
        """Aggregates all subsystem telemetry into a consolidated response."""
        return AllHardwareResponse(
            cpu=self.get_cpu_info(),
            memory=self.get_memory_info(),
            storage=self.get_storage_info(),
            gpu=self.get_gpu_info(),
            motherboard=self.get_motherboard_info(),
            os=self.get_os_info(),
            ram_upgrade=self.get_ram_upgrade_assessment(),
            timestamp=datetime.datetime.now().isoformat(),
            host_platform=platform.system(),
        )


# Singleton detector instance
detector = HardwareDetector()
