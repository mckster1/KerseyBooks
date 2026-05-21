@echo off
setlocal

set "ROOT=%~dp0.."
set "BACKEND=%ROOT%\backend"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

cd /d "%BACKEND%"
"%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload

endlocal
