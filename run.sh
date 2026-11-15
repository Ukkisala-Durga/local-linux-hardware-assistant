#!/usr/bin/env bash
# ==============================================================================
# Linux Laptop Hardware Q&A Assistant - Launcher Script
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "========================================================================"
echo " Starting Linux Laptop Hardware Q&A Assistant"
echo "========================================================================"

# 1. Virtual Environment Setup
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "[*] Creating Python virtual environment in $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

echo "[*] Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# 2. Dependency Installation
echo "[*] Checking and installing Python dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# 3. Verify System Inspection Utilities
echo "[*] Verifying available Linux inspection utilities..."
for tool in lscpu free lsblk lspci dmidecode; do
    if command -v "$tool" >/dev/null 2>&1; then
        echo "    [+] Found: $tool"
    else
        echo "    [-] Optional/Missing: $tool (fallback parser will be used)"
    fi
done

# 4. Check Optional Ollama Service
if curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "[+] Ollama detected at http://127.0.0.1:11434 (LLM synthesis enabled)"
else
    echo "[-] Ollama offline or not installed (Rule-based anti-hallucination fallback active)"
fi

# 5. Display Server Information
echo "========================================================================"
echo " Web Application URL : http://127.0.0.1:8000"
echo " FastAPI Swagger Docs: http://127.0.0.1:8000/docs"
echo " Interactive OpenAPI : http://127.0.0.1:8000/redoc"
echo "========================================================================"
echo "[*] Launching Uvicorn server..."
exec uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
