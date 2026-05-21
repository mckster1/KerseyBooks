@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "VENV=%ROOT%.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"
set "URL=http://localhost:8001"

echo === KerseyBooks ===
echo Root: %ROOT%

if not exist "%ROOT%.env" (
    copy "%ROOT%.env.example" "%ROOT%.env" >nul
    echo Created .env from .env.example.
)

if not exist "%PYTHON%" (
    echo Creating Python virtual environment...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo Failed to create virtual environment. Make sure Python is installed.
        pause
        exit /b 1
    )
)

echo Installing or updating dependencies...
"%PIP%" install -q -r "%BACKEND%\requirements.txt"
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

netstat -ano | findstr ":8001" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo Starting backend on %URL% ...
    start "KerseyBooks Backend" "%ROOT%scripts\run-backend.bat"
) else (
    echo Backend already appears to be running on %URL%.
)

echo Opening %URL% ...
timeout /t 3 /nobreak >nul
start "" "%URL%"

endlocal
