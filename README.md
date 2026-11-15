# Linux Laptop Hardware Q&A Assistant

An intelligent, secure, local natural-language conversational assistant that inspects a host Linux laptop's hardware specifications and answers user queries in plain English with zero hallucination.

Built with **FastAPI**, **Pydantic**, **psutil**, safe Linux system inspection utilities, and an optional **Ollama** local LLM reasoning layer backed by a deterministic, anti-hallucinating rule-based synthesizer.

---

## 1. Architecture & Design

Instead of letting an LLM guess or hallucinate hardware specifications, the assistant adheres to a deterministic, secure tool-calling pipeline:

```
+-------------------------------------------------------------------------+
|                        1. USER NATURAL INPUT                            |
|             "Can I upgrade my RAM, and how much can I add?"             |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
|                  2. INTENT ROUTER & CONTEXT RESOLVER                    |
|  - Identifies hardware category ('ram_upgrade', 'memory', 'cpu', etc.)  |
|  - Resolves multi-turn follow-ups ("How much is available?", "And GPU?")|
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
|                3. SECURE SYSTEM EXECUTION ENGINE                        |
|  - Validates command against strict ALLOW-LIST                          |
|  - Strictly enforces subprocess(shell=False) with 5-second timeouts     |
|  - Safe read-only path checks (blocks directory traversal)              |
|  - Privilege Fallback: dmidecode -> scoped sudo -> /sys/class/dmi/id    |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
|                 4. PARSER & SCHEMA NORMALIZER                           |
|  - Normalizes raw stdout (lscpu, lsblk -J, free -b, lspci, dmidecode)   |
|  - Maps into validated Pydantic models (MemoryInfo, CpuInfo, etc.)      |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
|                  5. CONTEXTUAL ANSWER SYNTHESIS                         |
|  - Primary: Local Ollama LLM with strict anti-hallucination bounds      |
|  - Automatic Fallback: High-precision Rule-Based Synthesizer            |
|  - Returns accurate natural English answer + structured JSON data       |
+-------------------------------------------------------------------------+
```

---

## 2. Key Engineering Challenges Addressed

### A. Security & Arbitrary Code Execution Prevention
- **Strict Allow-List**: Only explicitly registered, read-only system inspection commands (`lscpu`, `free`, `lsblk`, `lspci`, `uname`, `dmidecode`, `nvidia-smi`) can be invoked. Arbitrary commands or flags from user input or LLM generation are rejected with a security violation.
- **No Subshell Spawning (`shell=False`)**: System calls use direct OS execution (`execve`) via `subprocess.run(..., shell=False)`. Chaining (`&&`, `|`, `;`), flag injections, or shell expansions are impossible.
- **Path Traversal Protection**: Pseudo-filesystem file reads (`/proc`, `/sys`, `/etc/os-release`) are strictly validated against allowed path prefixes with canonicalized path resolution.
- **Execution Timeouts**: All system inspections enforce a 5-second timeout to prevent hangs.

### B. Privilege Escalation Strategy for `dmidecode`
Commands like `dmidecode` require `root` to inspect physical DMI/SMBIOS memory arrays. Running the entire assistant or web server as `root` is a severe security risk. The assistant solves this through a layered hierarchy:
1. **Direct `dmidecode`**: First attempts standard user execution.
2. **Scoped Sudo Helper**: If unprivileged execution fails, attempts non-interactive `sudo -n dmidecode -t memory` (which succeeds if a scoped rule in `/etc/sudoers.d/hardware-assistant` is provisioned).
3. **Non-Root Sysfs Fallbacks**: If permissions are denied, falls back to reading world-readable pseudo-files in `/sys/class/dmi/id/` (such as `board_vendor`, `board_name`, `product_name`, `bios_version`) and `/proc/meminfo`.
4. **Honest Caveat Reporting**: If physical slot counts or max capacity cannot be read due to permissions, the assistant explicitly states: *"Unable to verify physical RAM slots without root privileges (dmidecode). Please check manufacturer specifications or run with dmidecode permissions."*

### C. Output Normalization & Distro Portability
- Distro outputs vary significantly across Debian/Ubuntu, Fedora/RHEL, and Arch. The parser handles both JSON formats (`lsblk -J`) and fallback text parsing.
- Missing command discovery at startup via `shutil.which` dynamically configures the tool registry. If `lscpu` is missing, `/proc/cpuinfo` is automatically parsed.

### D. Multi-Turn Conversation & Follow-Up Context
- Maintains in-memory session history (`session_id`).
- Automatically resolves follow-up queries:
  - *User*: "How much RAM do I have?" -> Category: `memory`
  - *User*: "How much is currently available?" -> Resolves pronoun to previous `memory` topic.
  - *User*: "What about my GPU?" -> Switches context to `gpu`.
  - *User*: "Can I upgrade it?" -> Evaluates `ram_upgrade` based on prior memory context.

### E. RAM Upgrade Assessment Engine
Calculates:
- Installed RAM vs. Maximum supported board capacity.
- Total memory slots vs. populated slots vs. empty slots.
- Memory form factor (`SODIMM` vs. soldered `Row of chips` / `LPDDR`).
- Clear verdict:
  - **Upgradeable (Empty Slots)**: *"You have 1 empty memory slot available out of 2 total slots. You can add an additional stick without removing existing RAM."*
  - **Upgradeable (Module Replacement)**: *"All 2 slots are full, but the board supports up to 64 GB. You can upgrade by replacing existing sticks."*
  - **Non-Upgradeable (Soldered)**: *"RAM is soldered to the board (LPDDR); expandable memory slots are not available."*
  - **Inconclusive**: Explains exact missing telemetry without guessing.

---

## 3. Technology Stack

- **Backend**: Python 3.11+, FastAPI, Uvicorn, Pydantic v2, psutil, httpx
- **Frontend**: Modern responsive UI (HTML5, CSS3 with dark/light themes, Vanilla JavaScript fetch API)
- **AI Reasoning**: Local **Ollama** LLM (supports `llama3.2`, `qwen2.5`, `mistral`, `phi3`) with automatic deterministic rule-based fallback
- **Testing**: pytest, pytest-asyncio, FastAPI TestClient

---

## 4. Project Structure

```
linux-hardware-assistant/
├── app/
│   ├── __init__.py           # Package marker and version
│   ├── main.py               # FastAPI application, routing, static mounting
│   ├── hardware.py           # Hardware telemetry collectors and orchestrator
│   ├── commands.py           # Safe command allow-list and subprocess engine
│   ├── parser.py             # Distro CLI and /proc output parsers
│   ├── assistant.py          # Intent routing, follow-up context, Ollama + fallback synthesis
│   └── schemas.py            # Strictly validated Pydantic models
├── static/
│   ├── style.css             # Dark/Light theme, glassmorphism, responsive styles
│   └── script.js             # Telemetry fetching, chat messaging, copy-to-clipboard
├── templates/
│   └── index.html            # Single-page responsive dashboard and chat UI
├── tests/
│   ├── test_hardware.py      # Security, allow-list, privilege fallback, upgrade tests
│   ├── test_parser.py        # CLI output parsers (lscpu, free, lsblk, lspci, dmi)
│   └── test_api.py           # FastAPI endpoints, multi-turn follow-up chat tests
├── requirements.txt          # Production and testing Python dependencies
├── run.sh                    # Linux automated virtualenv setup and server launcher
├── run.bat                   # Windows development launcher
├── .gitignore                # Clean source control exclusions
└── README.md                 # Complete documentation
```

---

## 5. Installation and Execution

### Linux (Recommended Host)

1. **Clone the repository**:
   ```bash
   git clone <repo-url>
   cd Local-Linux-Hardware-Assistant
   ```

2. **Make the launch script executable and run**:
   ```bash
   chmod +x run.sh
   ./run.sh
   ```

   The script automatically:
   - Creates a Python virtual environment (`.venv`).
   - Installs required dependencies.
   - Probes system tools (`lscpu`, `free`, `lsblk`, `lspci`, `dmidecode`).
   - Checks for a running Ollama daemon.
   - Starts the Uvicorn server on `http://127.0.0.1:8000`.

3. **(Optional) Configure Scoped Sudo for `dmidecode`**:
   To allow deep memory slot inspection without password prompts:
   ```bash
   echo "$USER ALL=(ALL) NOPASSWD: /usr/sbin/dmidecode" | sudo tee /etc/sudoers.d/hardware-assistant
   sudo chmod 0440 /etc/sudoers.d/hardware-assistant
   ```

### Windows / macOS (Development & Testing)

1. **Run using Python**:
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
   Or simply double-click `run.bat`.

> **Note on Windows Host Development**: On Windows, `psutil` and `platform` provide host CPU, RAM, and disk partition information. For deep Linux sysfs and `dmidecode` inspection, run on a Linux laptop or Linux VM. All Linux parsers, command runners, and upgrade engines are 100% covered and verified via unit tests with real Linux telemetry fixtures.

---

## 6. Optional Local LLM (Ollama) Setup

The assistant includes zero-configuration automatic fallback to its built-in rule-based synthesizer. To enable local neural LLM reasoning:

1. Install Ollama:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```
2. Pull your preferred model (e.g. `llama3.2` or `qwen2.5:3b`):
   ```bash
   ollama run llama3.2
   ```
3. The assistant will automatically detect `http://127.0.0.1:11434` at runtime and switch to LLM synthesis mode.

---

## 7. Example Questions & Answers

| Question | Identified Category | Example Answer |
| :--- | :--- | :--- |
| **"How much RAM do I have?"** | `memory` | *"Your laptop has 16.0 GB of installed RAM. Currently 10.4 GB is available and 5.6 GB is used (35.0%)."* |
| **"How much is currently available?"** *(follow-up)* | `memory` | *"Approximately 10.4 GB of RAM (65.0% of total) is currently available for new processes."* |
| **"Is my SSD NVMe or SATA?"** | `storage` | *"Yes, your system uses NVMe SSD storage! Detected NVMe drive(s): nvme0n1 (Samsung SSD 980 500GB, 476.9 GB)."* |
| **"What is my processor model?"** | `cpu` | *"Your processor is 11th Gen Intel(R) Core(TM) i7-11800H @ 2.30GHz (x86_64) featuring 8 cores / 16 threads with L3 Cache: 24 MiB."* |
| **"How many CPU cores do I have?"** | `cpu` | *"Your CPU has 8 physical core(s) and 16 logical execution thread(s)."* |
| **"What GPU does my laptop have?"** | `gpu` | *"Your laptop is equipped with 2 graphics adapters: Intel TigerLake-H GT1 [UHD Graphics] \| NVIDIA GeForce RTX 3060 Laptop GPU with 6.0 GB VRAM (Driver: 535.154.05) [Temp: 48 °C]."* |
| **"Can I upgrade my RAM?"** | `ram_upgrade` | *"RAM can be upgraded. You have 1 empty memory slot available out of 2 total slots. You can add an additional module into the empty slot without removing your existing RAM. The motherboard supports up to 64 GB."* |
| **"What is my motherboard model?"** | `motherboard` | *"Your motherboard is manufactured by LENOVO, model: 20XY001VUS (Version SDK0T76530 WIN) running BIOS N32ET75W."* |
| **"What is my disk capacity?"** | `storage` | *"Your laptop has a total physical storage capacity of 1.4 TB. Drive breakdown: nvme0n1: 476.9 GB (NVMe SSD), sda: 931.5 GB (SATA Drive)."* |
| **"What Linux operating system am I running?"** | `os` | *"You are running Ubuntu 22.04.3 LTS on architecture x86_64 (Kernel: 6.5.0-35-generic, system uptime: 3d 4h 12m)."* |
| **"Show my complete hardware details."** | `all_hardware` | Full formatted breakdown of OS, CPU, RAM, Storage, Graphics, and Upgradeability. |

---

## 8. REST API Documentation

FastAPI auto-generates interactive Swagger documentation at **`http://127.0.0.1:8000/docs`** and ReDoc at **`http://127.0.0.1:8000/redoc`**.

### Endpoints Overview

- `GET /` - Serves the web-based chatbot dashboard.
- `GET /api/health` - System health, detected platform, tool presence, and Ollama status.
- `GET /api/hardware` - Complete detected hardware telemetry (`AllHardwareResponse`).
- `GET /api/hardware/cpu` - CPU model, core counts, threads, clock frequencies, and cache.
- `GET /api/hardware/memory` - Total, used, and available RAM, swap space, and memory slots.
- `GET /api/hardware/storage` - Storage block devices, NVMe vs. SATA classification, and total disk capacity.
- `GET /api/hardware/gpu` - Graphics adapters (NVIDIA, AMD, Intel), VRAM, and driver details.
- `GET /api/hardware/motherboard` - Motherboard manufacturer, product model, and BIOS info.
- `GET /api/hardware/os` - Linux distribution, kernel release, and system uptime.
- `GET /api/hardware/ram-upgrade` - Rigorous RAM upgrade assessment with slot analysis.
- `POST /api/chat` - Natural language conversational query endpoint.
  - Request: `{"message": "How much RAM do I have?", "session_id": "optional-uuid"}`
  - Response: `{"answer": "...", "category": "memory", "data": {...}, "source": "rule_based_fallback", "session_id": "..."}`
- `POST /api/chat/clear` - Clears conversational history and session memory.

---

## 9. Automated Testing

The project includes 31 comprehensive unit and integration tests using `pytest`:

```bash
python -m pytest -v
```

### Test Coverage Highlights:
- **`tests/test_parser.py`**: Validates parsers for `lscpu`, `free`, `lsblk -J`, `lspci`, `dmidecode -t memory`, `dmidecode -t baseboard`, `/proc/cpuinfo`, `/proc/meminfo`, and `/etc/os-release`.
- **`tests/test_hardware.py`**: Tests command allow-list rejection, `shell=False` enforcement, path traversal defense, hybrid GPU resolution, empty slot vs. soldered RAM upgrade verdicts, and permission fallback reporting.
- **`tests/test_api.py`**: Tests FastAPI routing, health endpoints, hardware REST contracts, multi-turn follow-up resolution, and session clearing.

---

## 10. License & Author

Developed as an interview assignment for a Senior Python Developer, AI Engineer, and Full-Stack Developer position.
Distributed under the MIT License.
