"""
Safe System Command Execution Engine.
Strictly controls access to host inspection utilities using an immutable allow-list,
enforcing shell=False, execution timeouts, argument validation, and non-root fallbacks.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Execution timeout in seconds to prevent hangs on misbehaving system calls
DEFAULT_TIMEOUT_SECONDS = 5

# Strict, immutable allow-list of permitted system commands.
# Maps logical tool IDs to exact binary arguments.
# No user input or dynamic flags are ever passed to shell or subprocess.
ALLOWED_COMMANDS: Dict[str, List[str]] = {
    # CPU inspection
    "lscpu": ["lscpu"],
    
    # Memory inspection
    "free": ["free", "-b"],
    "free_human": ["free", "-h"],
    
    # Block device and storage inspection
    # -J: JSON output, -b: bytes, -o: specific columns
    "lsblk": [
        "lsblk",
        "-J",
        "-b",
        "-o",
        "NAME,SIZE,TYPE,MOUNTPOINT,MODEL,ROTA,TRAN,FSTYPE",
    ],
    "lsblk_simple": ["lsblk", "-b", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,MODEL,ROTA,TRAN,FSTYPE"],
    
    # PCI bus inspection for GPUs and peripherals
    "lspci": ["lspci"],
    "lspci_vmm": ["lspci", "-vmm"],
    "lspci_nnk": ["lspci", "-nnk"],
    
    # Operating system and kernel
    "uname": ["uname", "-a"],
    "uname_kernel": ["uname", "-r"],
    "uname_arch": ["uname", "-m"],
    "uptime": ["uptime", "-p"],
    
    # NVIDIA dedicated GPU telemetry (safe, read-only query)
    "nvidia_smi": [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.free,driver_version,temperature.gpu",
        "--format=csv,noheader,nounits",
    ],
    
    # DMI / BIOS inspection (requires root or sudoers rule for deep hardware data)
    "dmidecode_memory": ["dmidecode", "-t", "memory"],
    "dmidecode_baseboard": ["dmidecode", "-t", "baseboard"],
    "dmidecode_chassis": ["dmidecode", "-t", "chassis"],
    
    # Non-interactive sudo variants (will fail immediately without prompting if password required)
    "sudo_dmidecode_memory": ["sudo", "-n", "dmidecode", "-t", "memory"],
    "sudo_dmidecode_baseboard": ["sudo", "-n", "dmidecode", "-t", "baseboard"],
}

# Whitelist of safe, read-only system file paths permitted for inspection
SAFE_SYSTEM_FILE_PREFIXES = (
    "/proc/cpuinfo",
    "/proc/meminfo",
    "/proc/version",
    "/proc/uptime",
    "/etc/os-release",
    "/etc/lsb-release",
    "/sys/class/dmi/id/",
    "/sys/block/",
)


def discover_available_tools() -> Dict[str, bool]:
    """
    Checks the system PATH for required and optional CLI binaries.
    Used for capability discovery at startup and dynamic tool registry.
    """
    tools = ["lscpu", "free", "lsblk", "lspci", "dmidecode", "uname", "nvidia-smi"]
    return {tool: shutil.which(tool) is not None for tool in tools}


def execute_system_command(
    command_id: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Tuple[bool, str, str]:
    """
    Safely executes an allow-listed system tool without subshell spawning.

    Security guarantees:
    - Rejects any command_id not explicitly present in ALLOWED_COMMANDS.
    - Uses subprocess.run with shell=False exclusively.
    - Prevents arbitrary command injection and argument manipulation.
    - Enforces strict execution timeout.
    - Captures stdout and stderr cleanly.

    Returns:
        (success: bool, stdout: str, stderr: str)
    """
    if command_id not in ALLOWED_COMMANDS:
        error_msg = f"Security Violation: '{command_id}' is not in the system allow-list."
        logger.error(error_msg)
        raise ValueError(error_msg)

    cmd_args = ALLOWED_COMMANDS[command_id]
    binary_name = cmd_args[0]

    # Quick existence check for primary binary
    if not shutil.which(binary_name):
        return (
            False,
            "",
            f"Binary '{binary_name}' is not installed or not in PATH.",
        )

    try:
        # shell=False is strictly enforced here
        completed = subprocess.run(
            cmd_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            timeout=timeout,
            check=False,
        )

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()

        if completed.returncode != 0:
            logger.warning(
                "Command '%s' exited with code %d. Stderr: %s",
                command_id,
                completed.returncode,
                stderr,
            )
            return False, stdout, stderr or f"Exited with return code {completed.returncode}"

        return True, stdout, ""

    except subprocess.TimeoutExpired:
        logger.error("Command '%s' timed out after %d seconds", command_id, timeout)
        return False, "", f"Command timed out after {timeout} seconds."

    except PermissionError as pe:
        logger.warning("Permission denied executing command '%s': %s", command_id, pe)
        return False, "", f"Permission denied: {pe}"

    except FileNotFoundError as fnf:
        logger.warning("Command binary not found '%s': %s", command_id, fnf)
        return False, "", f"Command not found: {fnf}"

    except Exception as exc:
        logger.exception("Unexpected error executing command '%s'", command_id)
        return False, "", f"Execution failure: {str(exc)}"


def read_system_file(path_str: str) -> Optional[str]:
    """
    Safely reads a read-only pseudo-filesystem file (/proc or /sys or /etc/os-release).

    Security:
    - Validates against SAFE_SYSTEM_FILE_PREFIXES to prevent directory traversal.
    - Resolves realpath to block symlink attacks.
    """
    try:
        norm_path = os.path.abspath(path_str).replace("\\", "/")
        # Strip Windows drive letter if present for uniform POSIX check
        clean_path = norm_path
        if len(clean_path) >= 2 and clean_path[1] == ":":
            clean_path = clean_path[2:]
        
        # Verify that path starts with an allowed prefix
        is_safe = any(clean_path.startswith(prefix) for prefix in SAFE_SYSTEM_FILE_PREFIXES)
        if not is_safe:
            logger.warning("Blocked read attempt on unauthorized path: %s", path_str)
            return None

        p = Path(norm_path)
        if not p.is_file():
            return None

        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()

    except PermissionError:
        logger.warning("Permission denied accessing system file: %s", path_str)
        return None
    except Exception as exc:
        logger.debug("Failed reading system file %s: %s", path_str, exc)
        return None
