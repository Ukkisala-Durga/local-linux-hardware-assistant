@echo off
REM ==============================================================================
REM Linux Laptop Hardware Q&A Assistant - Windows Launcher Script
REM ==============================================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ========================================================================
echo  Starting Linux Laptop Hardware Q&A Assistant
echo ========================================================================

REM 1. Virtual Environment Setup
if not exist ".venv" (
    echo [*] Creating Python virtual environment in .venv...
    python -m venv .venv
)

echo [*] Activating virtual environment...
call .venv\Scripts\activate.bat 2>nul || (
    echo [!] Could not activate virtualenv, continuing with system Python...
)

REM 2. Dependency Installation
echo [*] Checking dependencies...
python -m pip install -r requirements.txt --quiet

REM 3. Display Server URLs
echo ========================================================================
echo  Web Application URL : http://127.0.0.1:8000
echo  FastAPI Swagger Docs: http://127.0.0.1:8000/docs
echo  Interactive OpenAPI : http://127.0.0.1:8000/redoc
echo ========================================================================
echo [*] Launching Uvicorn server...
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
