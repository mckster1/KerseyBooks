# KerseyBooks launcher for Windows
# Usage: .\scripts\start.ps1

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent

Write-Host "=== KerseyBooks ===" -ForegroundColor Cyan
Write-Host "Root: $Root"

# 1. Create .env if missing
$envFile    = Join-Path $Root ".env"
$envExample = Join-Path $Root ".env.example"
if (-not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Host ".env created - add LLM_API_KEY to enable Ask AI" -ForegroundColor Yellow
}

# 2. Create venv if missing
$venvPath = Join-Path $Root ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv $venvPath
}

# 3. Install dependencies
$pip        = Join-Path $venvPath "Scripts\pip.exe"
$backendDir = Join-Path $Root "backend"
Write-Host "Installing dependencies..." -ForegroundColor Yellow
& $pip install -q -r (Join-Path $backendDir "requirements.txt")

# 4. Start server
$uvicorn = Join-Path $venvPath "Scripts\uvicorn.exe"
Write-Host ""
Write-Host "Starting KerseyBooks on http://localhost:8001" -ForegroundColor Green
Write-Host "Open http://localhost:8001 in your browser."
Write-Host "Press Ctrl+C to stop."
Write-Host ""

Set-Location $backendDir
& $uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
