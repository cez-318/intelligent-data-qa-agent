@echo off
setlocal
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Missing .venv. See README.md.
    exit /b 1
)
echo Intelligent QA: http://127.0.0.1:8000
echo Requires configured LLM, MySQL, Embedding, Elasticsearch and Qdrant.
echo No rule-based fallback. Press Ctrl+C to stop.
"%~dp0.venv\Scripts\python.exe" "%~dp0backend\main.py"
