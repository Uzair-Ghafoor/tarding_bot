# One-time AWS Windows setup for Exness MT5 bot
# Run in PowerShell as Administrator on your EC2 instance

$ErrorActionPreference = "Stop"
Write-Host "=== Exness MT5 Bot — AWS setup ===" -ForegroundColor Cyan

# 1. Python 3.12
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Python 3.12..."
    winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# 2. Project venv
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env — EDIT IT with your Exness demo credentials before running." -ForegroundColor Yellow
}

python -m venv .venv
& ".\.venv\Scripts\pip.exe" install --upgrade pip
& ".\.venv\Scripts\pip.exe" install -r requirements.txt

New-Item -ItemType Directory -Force -Path "logs","data" | Out-Null

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Green
Write-Host "  1. Install Exness MT5 from https://www.exness.com/metatrader-5/"
Write-Host "  2. Log into your DEMO account in MT5 (Algo Trading must be ON)"
Write-Host "  3. Edit mt5\.env with login, password, server from Exness Personal Area"
Write-Host "  4. Run:  .\.venv\Scripts\python.exe test_connection.py"
Write-Host "  5. Run:  .\run_bot.ps1"
Write-Host "  6. Optional 24/7:  .\install_scheduled_task.ps1"
