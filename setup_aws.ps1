# One-time AWS Windows setup for Exness MT5 bot
# Run in PowerShell as Administrator:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#   .\setup_aws.ps1

$ErrorActionPreference = "Stop"
Write-Host "=== Exness MT5 Bot - AWS setup ===" -ForegroundColor Cyan

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# 1. Python 3.12
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Python 3.12..."
    winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Python not found. Install from https://www.python.org/downloads/ then re-run this script." -ForegroundColor Red
    exit 1
}

# 2. .env
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env - EDIT IT with your Exness demo credentials before running." -ForegroundColor Yellow
}

# 3. Virtual environment + packages
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\pip.exe" install -r requirements.txt

New-Item -ItemType Directory -Force -Path "logs", "data" | Out-Null

Write-Host ""
Write-Host "Setup done. Next steps:" -ForegroundColor Green
Write-Host "  1. Log into Exness DEMO in MT5 (Algo Trading ON)"
Write-Host "  2. Edit .env:  notepad .env"
Write-Host "  3. Test:       .\.venv\Scripts\python.exe test_connection.py"
Write-Host "  4. Run bot:    .\run_bot.ps1"
