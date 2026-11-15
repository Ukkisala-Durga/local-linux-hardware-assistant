"""
Unit Tests for Hardware Telemetry Engine and Security Controls.
Verifies command allow-list enforcement, privilege error handling,
RAM upgrade assessments, and cross-platform fallbacks.
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from app.commands import (
    ALLOWED_COMMANDS,
    execute_system_command,
    read_system_file,
)
from app.hardware import HardwareDetector
from app.schemas import MemoryInfo, MemorySlot


# ==================== SECURITY & COMMAND TESTS ====================

def test_command_allow_list_rejection():
    """Confirms arbitrary shell commands are strictly rejected."""
    unauthorized_commands = [
        "rm -rf /",
        "cat /etc/shadow",
        "curl http://malicious.site",
        "sh",
        "bash",
        "sudo rm -rf",
    ]
    for cmd in unauthorized_commands:
        with pytest.raises(ValueError, match="Security Violation"):
            execute_system_command(cmd)


def test_command_execution_shell_is_false():
    """Ensures shell=False is strictly enforced."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="test", stderr="")
        with patch("shutil.which", return_value="/usr/bin/lscpu"):
            ok, out, _ = execute_system_command("lscpu")
            assert ok is True
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            assert kwargs.get("shell") is False


def test_path_traversal_blocked_in_file_reader():
    """Ensures read_system_file rejects paths outside permitted prefixes."""
    dangerous_paths = [
        "../../etc/passwd",
        "/etc/shadow",
        "/home/user/.ssh/id_rsa",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
    ]
    for p in dangerous_paths:
        res = read_system_file(p)
        assert res is None


# ==================== HARDWARE DETECTOR UNIT TESTS ====================

@pytest.fixture
def linux_detector():
    """Provides a HardwareDetector forced into Linux mode."""
    det = HardwareDetector()
    det.is_linux = True
    return det


def test_get_cpu_info_with_lscpu(linux_detector):
    sample_lscpu = """
Architecture: x86_64
Model name: AMD Ryzen 7 5800H with Radeon Graphics
CPU(s): 16
Core(s) per socket: 8
Socket(s): 1
CPU max MHz: 4400.0000
CPU min MHz: 1200.0000
"""
    with patch("app.hardware.execute_system_command", return_value=(True, sample_lscpu, "")):
        cpu = linux_detector.get_cpu_info()
        assert cpu.model == "AMD Ryzen 7 5800H with Radeon Graphics"
        assert cpu.physical_cores == 8
        assert cpu.logical_threads == 16
        assert cpu.max_mhz == 4400.0


def test_get_cpu_info_fallback_proc_cpuinfo(linux_detector):
    sample_cpuinfo = """
model name	: AMD Ryzen 5 3600 6-Core Processor
cpu cores	: 6
cpu MHz		: 3600.000
"""
    # lscpu fails, /proc/cpuinfo succeeds
    with patch("app.hardware.execute_system_command", return_value=(False, "", "not found")), \
         patch("app.hardware.read_system_file", return_value=sample_cpuinfo):
        cpu = linux_detector.get_cpu_info()
        assert "AMD Ryzen 5" in cpu.model
        assert cpu.physical_cores == 6


def test_get_storage_info_classifies_nvme_and_sata(linux_detector):
    sample_lsblk = {
        "blockdevices": [
            {
                "name": "nvme0n1",
                "size": 512110190592,
                "type": "disk",
                "model": "Samsung SSD 980 500GB",
                "rota": 0,
                "tran": "nvme",
            },
            {
                "name": "sda",
                "size": 1000204886016,
                "type": "disk",
                "model": "Crucial MX500",
                "rota": 0,
                "tran": "sata",
            },
        ]
    }
    with patch("app.hardware.execute_system_command", return_value=(True, json.dumps(sample_lsblk), "")):
        storage = linux_detector.get_storage_info()
        assert storage.nvme_count == 1
        assert storage.sata_count == 1
        assert len(storage.devices) == 2
        assert "TB" in storage.total_capacity_formatted or "GB" in storage.total_capacity_formatted


def test_get_gpu_info_hybrid_graphics(linux_detector):
    sample_lspci = """
00:02.0 VGA compatible controller: Intel Corporation UHD Graphics (rev 05)
01:00.0 3D controller: NVIDIA Corporation GA106M [GeForce RTX 3060 Mobile] (rev a1)
"""
    sample_smi = "NVIDIA GeForce RTX 3060 Laptop GPU, 6144, 4500, 535.154.05, 52"

    def mock_cmd(cmd_id):
        if cmd_id == "lspci":
            return True, sample_lspci, ""
        if cmd_id == "nvidia_smi":
            return True, sample_smi, ""
        return False, "", "error"

    with patch("app.hardware.execute_system_command", side_effect=mock_cmd):
        gpu_info = linux_detector.get_gpu_info()
        assert gpu_info.count == 2
        nvidia_gpu = next(g for g in gpu_info.devices if g.vendor == "NVIDIA")
        assert nvidia_gpu.vram_formatted == "6.0 GB"
        assert nvidia_gpu.driver_version == "535.154.05"
        assert nvidia_gpu.temperature == "52 °C"


def test_ram_upgrade_assessment_empty_slot_available(linux_detector):
    """Case 1: Empty slot available -> easily upgradeable."""
    mock_mem = MemoryInfo(
        total_bytes=17179869184,
        total_formatted="16.0 GB",
        used_bytes=8589934592,
        used_formatted="8.0 GB",
        available_bytes=8589934592,
        available_formatted="8.0 GB",
        free_bytes=4000000000,
        free_formatted="4.0 GB",
        percent_used=50.0,
        swap_total_formatted="2.0 GB",
        swap_used_formatted="0 B",
        total_slots=2,
        populated_slots=1,
        empty_slots=1,
        max_capacity_formatted="64 GB",
        slots=[
            MemorySlot(locator="DIMM 0", size="16 GB", ram_type="DDR4", form_factor="SODIMM", is_populated=True),
            MemorySlot(locator="DIMM 1", size="No Module Installed", form_factor="SODIMM", is_populated=False),
        ],
    )
    with patch.object(linux_detector, "get_memory_info", return_value=mock_mem):
        assessment = linux_detector.get_ram_upgrade_assessment()
        assert assessment.is_upgradeable is True
        assert assessment.empty_slots == 1
        assert "empty memory slot" in assessment.assessment_summary.lower()
        assert assessment.confidence == "high"


def test_ram_upgrade_assessment_all_slots_populated(linux_detector):
    """Case 2: All slots full, but max capacity is higher -> upgradeable by replacing sticks."""
    mock_mem = MemoryInfo(
        total_bytes=17179869184,
        total_formatted="16.0 GB",
        used_bytes=8589934592,
        used_formatted="8.0 GB",
        available_bytes=8589934592,
        available_formatted="8.0 GB",
        free_bytes=4000000000,
        free_formatted="4.0 GB",
        percent_used=50.0,
        swap_total_formatted="2.0 GB",
        swap_used_formatted="0 B",
        total_slots=2,
        populated_slots=2,
        empty_slots=0,
        max_capacity_formatted="64 GB",
        slots=[
            MemorySlot(locator="DIMM 0", size="8 GB", ram_type="DDR4", form_factor="SODIMM", is_populated=True),
            MemorySlot(locator="DIMM 1", size="8 GB", ram_type="DDR4", form_factor="SODIMM", is_populated=True),
        ],
    )
    with patch.object(linux_detector, "get_memory_info", return_value=mock_mem):
        assessment = linux_detector.get_ram_upgrade_assessment()
        assert assessment.is_upgradeable is True
        assert assessment.empty_slots == 0
        assert "replace" in assessment.recommendation.lower() or "replacing" in assessment.assessment_summary.lower()


def test_ram_upgrade_assessment_soldered_memory(linux_detector):
    """Case 3: Soldered memory chips -> not upgradeable."""
    mock_mem = MemoryInfo(
        total_bytes=17179869184,
        total_formatted="16.0 GB",
        used_bytes=8589934592,
        used_formatted="8.0 GB",
        available_bytes=8589934592,
        available_formatted="8.0 GB",
        free_bytes=4000000000,
        free_formatted="4.0 GB",
        percent_used=50.0,
        swap_total_formatted="2.0 GB",
        swap_used_formatted="0 B",
        total_slots=1,
        populated_slots=1,
        empty_slots=0,
        max_capacity_formatted="16.0 GB",
        slots=[
            MemorySlot(locator="Onboard", size="16 GB", ram_type="LPDDR4X", form_factor="Row of chips", is_populated=True),
        ],
    )
    with patch.object(linux_detector, "get_memory_info", return_value=mock_mem):
        assessment = linux_detector.get_ram_upgrade_assessment()
        assert assessment.is_upgradeable is False
        assert "soldered" in assessment.assessment_summary.lower()


def test_ram_upgrade_assessment_dmidecode_permission_denied(linux_detector):
    """Case 4: No root access for dmidecode -> reports honest caveat."""
    mock_mem = MemoryInfo(
        total_bytes=17179869184,
        total_formatted="16.0 GB",
        used_bytes=8589934592,
        used_formatted="8.0 GB",
        available_bytes=8589934592,
        available_formatted="8.0 GB",
        free_bytes=4000000000,
        free_formatted="4.0 GB",
        percent_used=50.0,
        swap_total_formatted="2.0 GB",
        swap_used_formatted="0 B",
        total_slots=None,
        populated_slots=None,
        empty_slots=None,
        max_capacity_formatted=None,
        slots=[],
    )
    with patch.object(linux_detector, "get_memory_info", return_value=mock_mem):
        assessment = linux_detector.get_ram_upgrade_assessment()
        assert assessment.is_upgradeable is None
        assert assessment.confidence == "low"
        assert "dmidecode" in assessment.assessment_summary or "privileges" in assessment.assessment_summary
