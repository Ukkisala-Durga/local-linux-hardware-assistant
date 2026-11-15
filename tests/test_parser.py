"""
Automated Unit Tests for Telemetry Parsers and Normalizers.
Validates extraction of CPU, Memory, Storage, GPU, Motherboard, and OS telemetry
using real-world sample command outputs and pseudo-filesystem fixtures.
"""

import json
import pytest
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


def test_format_bytes():
    assert format_bytes(0) == "0 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1024 * 1024 * 512) == "512.0 MB"
    assert format_bytes(1024 * 1024 * 1024 * 16) == "16.0 GB"


def test_parse_lscpu():
    sample_output = """
Architecture:                    x86_64
CPU op-mode(s):                  32-bit, 64-bit
Address sizes:                   39 bits physical, 48 bits virtual
Byte Order:                      Little Endian
CPU(s):                          16
On-line CPU(s) list:             0-15
Vendor ID:                       GenuineIntel
Model name:                      11th Gen Intel(R) Core(TM) i7-11800H @ 2.30GHz
CPU family:                      6
Model:                           141
Thread(s) per core:              2
Core(s) per socket:              8
Socket(s):                       1
Stepping:                        1
CPU max MHz:                     4600.0000
CPU min MHz:                     800.0000
BogoMIPS:                        4608.00
Virtualization:                  VT-x
L1d cache:                       384 KiB (8 instances)
L1i cache:                       256 KiB (8 instances)
L2 cache:                        10 MiB (8 instances)
L3 cache:                        24 MiB (1 instance)
"""
    result = parse_lscpu(sample_output)
    assert result["model"] == "11th Gen Intel(R) Core(TM) i7-11800H @ 2.30GHz"
    assert result["architecture"] == "x86_64"
    assert result["vendor"] == "GenuineIntel"
    assert result["physical_cores"] == 8
    assert result["logical_threads"] == 16
    assert result["max_mhz"] == 4600.0
    assert result["min_mhz"] == 800.0
    assert result["virtualization"] == "VT-x"
    assert result["l3_cache"] == "24 MiB (1 instance)"


def test_parse_proc_cpuinfo():
    sample_cpuinfo = """
processor	: 0
vendor_id	: GenuineIntel
cpu family	: 6
model		: 141
model name	: 11th Gen Intel(R) Core(TM) i7-11800H @ 2.30GHz
stepping	: 1
cpu MHz		: 2300.000
cache size	: 24576 KB
physical id	: 0
siblings	: 2
core id		: 0
cpu cores	: 8

processor	: 1
vendor_id	: GenuineIntel
cpu family	: 6
model		: 141
model name	: 11th Gen Intel(R) Core(TM) i7-11800H @ 2.30GHz
stepping	: 1
cpu MHz		: 2300.000
cache size	: 24576 KB
physical id	: 0
siblings	: 2
core id		: 0
cpu cores	: 8
"""
    result = parse_proc_cpuinfo(sample_cpuinfo)
    assert result["model"] == "11th Gen Intel(R) Core(TM) i7-11800H @ 2.30GHz"
    assert result["physical_cores"] == 8
    assert result["logical_threads"] == 2
    assert result["current_mhz"] == 2300.0


def test_parse_proc_meminfo():
    sample_meminfo = """
MemTotal:       16301880 kB
MemFree:         4829124 kB
MemAvailable:   11245620 kB
Buffers:          541280 kB
Cached:          6412000 kB
SwapTotal:       2097148 kB
SwapFree:        2097148 kB
"""
    result = parse_proc_meminfo(sample_meminfo)
    assert result["total_bytes"] == 16301880 * 1024
    assert result["available_bytes"] == 11245620 * 1024
    assert "GB" in result["total_formatted"]
    assert "GB" in result["available_formatted"]
    assert result["percent_used"] > 0


def test_parse_free():
    sample_free = """
               total        used        free      shared  buff/cache   available
Mem:     16718725120  4194304000  5000000000   104857600  7524421120 12000000000
Swap:     2147483648           0  2147483648
"""
    result = parse_free(sample_free)
    assert result["total_bytes"] == 16718725120
    assert result["used_bytes"] == 4194304000
    assert result["available_bytes"] == 12000000000
    assert result["status"] == "ok"


def test_parse_lsblk():
    sample_lsblk_json = {
        "blockdevices": [
            {
                "name": "nvme0n1",
                "size": 512110190592,
                "type": "disk",
                "mountpoint": None,
                "model": "SAMSUNG MZVL2512HCJQ-00B00",
                "rota": 0,
                "tran": "nvme",
                "fstype": None,
                "children": [
                    {
                        "name": "nvme0n1p1",
                        "size": 1073741824,
                        "type": "part",
                        "mountpoint": "/boot/efi",
                        "model": None,
                        "rota": 0,
                        "tran": None,
                        "fstype": "vfat",
                    },
                    {
                        "name": "nvme0n1p2",
                        "size": 511036448768,
                        "type": "part",
                        "mountpoint": "/",
                        "model": None,
                        "rota": 0,
                        "tran": None,
                        "fstype": "ext4",
                    },
                ],
            },
            {
                "name": "sda",
                "size": 1000204886016,
                "type": "disk",
                "mountpoint": None,
                "model": "ST1000LM048-2E7172",
                "rota": 1,
                "tran": "sata",
                "fstype": None,
            },
            {
                "name": "loop0",
                "size": 104857600,
                "type": "loop",
                "mountpoint": "/snap/core/123",
                "rota": 0,
                "tran": None,
                "fstype": "squashfs",
            },
        ]
    }
    devices = parse_lsblk(json.dumps(sample_lsblk_json))
    
    # Check that loop device is filtered out
    assert all("loop" not in d["name"] for d in devices)

    nvme_dev = next(d for d in devices if d["name"] == "nvme0n1")
    assert nvme_dev["is_nvme"] is True
    assert nvme_dev["is_ssd"] is True
    assert nvme_dev["is_rotational"] is False
    assert nvme_dev["transport"] == "nvme"

    sata_dev = next(d for d in devices if d["name"] == "sda")
    assert sata_dev["is_nvme"] is False
    assert sata_dev["is_rotational"] is True
    assert sata_dev["transport"] == "sata"


def test_parse_lspci():
    sample_lspci = """
00:00.0 Host bridge: Intel Corporation 11th Gen Core Processor Host Bridge/DRAM Registers (rev 05)
00:02.0 VGA compatible controller: Intel Corporation TigerLake-H GT1 [UHD Graphics] (rev 01)
01:00.0 3D controller: NVIDIA Corporation GA106M [GeForce RTX 3060 Mobile / Max-Q] (rev a1)
02:00.0 Network controller: Intel Corporation Wi-Fi 6 AX201 160MHz (rev 20)
"""
    gpus = parse_lspci(sample_lspci)
    assert len(gpus) == 2
    vendors = [g["vendor"] for g in gpus]
    assert "Intel" in vendors
    assert "NVIDIA" in vendors


def test_parse_nvidia_smi():
    sample_smi = "NVIDIA GeForce RTX 3060 Laptop GPU, 6144, 4800, 535.154.05, 48"
    gpus = parse_nvidia_smi(sample_smi)
    assert len(gpus) == 1
    assert gpus[0]["name"] == "NVIDIA GeForce RTX 3060 Laptop GPU"
    assert gpus[0]["vram_formatted"] == "6.0 GB"
    assert gpus[0]["driver_version"] == "535.154.05"
    assert gpus[0]["temperature"] == "48 °C"


def test_parse_dmidecode_memory():
    sample_dmi = """
# dmidecode 3.3
Getting SMBIOS data from sysfs.
SMBIOS 3.3.0 present.

Handle 0x002B, DMI type 16, 23 bytes
Physical Memory Array
	Location: System Board
	Use: System Memory
	Error Correction Type: None
	Maximum Capacity: 64 GB
	Error Information Handle: Not Provided
	Number Of Devices: 2

Handle 0x002C, DMI type 17, 92 bytes
Memory Device
	Array Handle: 0x002B
	Error Information Handle: Not Provided
	Total Width: 64 bits
	Data Width: 64 bits
	Size: 16 GB
	Form Factor: SODIMM
	Set: None
	Locator: ChannelA-DIMM0
	Bank Locator: BANK 0
	Type: DDR4
	Type Detail: Synchronous Unbuffered (Unregistered)
	Speed: 3200 MT/s
	Manufacturer: Samsung
	Serial Number: 41B37281
	Asset Tag: 9876543210
	Part Number: M471A2K43EB1-CWE
	Rank: 1
	Configured Memory Speed: 3200 MT/s

Handle 0x002D, DMI type 17, 92 bytes
Memory Device
	Array Handle: 0x002B
	Error Information Handle: Not Provided
	Total Width: Unknown
	Data Width: Unknown
	Size: No Module Installed
	Form Factor: SODIMM
	Set: None
	Locator: ChannelB-DIMM0
	Bank Locator: BANK 1
	Type: Unknown
	Type Detail: Unknown
	Speed: Unknown
	Manufacturer: Not Specified
"""
    result = parse_dmidecode_memory(sample_dmi)
    assert result["max_capacity"] == "64 GB"
    assert result["total_slots"] == 2
    assert result["populated_slots"] == 1
    assert result["empty_slots"] == 1
    assert len(result["slots"]) == 2
    assert result["slots"][0]["is_populated"] is True
    assert result["slots"][0]["ram_type"] == "DDR4"
    assert result["slots"][1]["is_populated"] is False


def test_parse_dmidecode_baseboard():
    sample_baseboard = """
Handle 0x0002, DMI type 2, 15 bytes
Base Board Information
	Manufacturer: LENOVO
	Product Name: 20XY001VUS
	Version: SDK0T76530 WIN
	Serial Number: L1HF18R007Z
	Asset Tag: Not Available
"""
    result = parse_dmidecode_baseboard(sample_baseboard)
    assert result["manufacturer"] == "LENOVO"
    assert result["product_name"] == "20XY001VUS"
    assert result["version"] == "SDK0T76530 WIN"
    # Serial number is masked
    assert "L1" in result["serial_number"]
    assert "*" in result["serial_number"]


def test_parse_os_release():
    sample_os = """
NAME="Ubuntu"
VERSION="22.04.3 LTS (Jammy Jellyfish)"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 22.04.3 LTS"
VERSION_ID="22.04"
"""
    result = parse_os_release(sample_os)
    assert result["distro_name"] == "Ubuntu 22.04.3 LTS"
    assert result["distro_version"] == "22.04.3 LTS (Jammy Jellyfish)"
    assert result["distro_id"] == "ubuntu"


def test_parse_uname():
    sample_uname = "Linux ubuntu-laptop 6.5.0-35-generic #35~22.04.1-Ubuntu SMP PREEMPT_DYNAMIC x86_64"
    result = parse_uname(sample_uname)
    assert result["kernel_version"] == "6.5.0-35-generic"
    assert result["architecture"] == "x86_64"
    assert result["hostname"] == "ubuntu-laptop"
