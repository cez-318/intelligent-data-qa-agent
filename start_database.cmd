@echo off
setlocal
cd /d "%~dp0"
docker compose -f compose.mysql.yaml up -d --wait --wait-timeout 120
