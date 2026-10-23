@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Missing .venv. See README.md.
    exit /b 1
)
echo Real historical UCI retail data: http://127.0.0.1:8000
echo Start the project services first. Stop another app on port 8000 before switching.
"%~dp0.venv\Scripts\python.exe" "%~dp0tools\run_retail.py" serve
