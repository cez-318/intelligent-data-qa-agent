@echo off
setlocal
"%~dp0.venv\Scripts\python.exe" "%~dp0tools\verify.py"
exit /b %errorlevel%
