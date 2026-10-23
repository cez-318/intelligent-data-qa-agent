@echo off
setlocal
cd /d "%~dp0"
docker compose -f compose.mysql.yaml -f compose.search.yaml up -d
if errorlevel 1 exit /b 1
echo Services started. Embedding and search may need time to become ready.
