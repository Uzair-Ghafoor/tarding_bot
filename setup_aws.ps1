# One-time AWS Windows setup for Exness MT5 bot
# Run in PowerShell as Administrator:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#   .\setup_aws.ps1

$ErrorActionPreference = "Stop"
Write-Host "=== Exness MT5 Bot - AWS setup ===" -ForegroundColor Cyan

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Test-Python {
    return [bool](Get-Command python -ErrorAction SilentlyContinue)
}

function Install-Python312 {
    Write-Host "Python not found. Downloading Python 3.12 installer..."
    $installer = Join-Path $env:TEMP "python-3.12.7-amd64.exe"
    $url = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    Write-Host "Installing Python (this may take a minute)..."
    Start-Process -FilePath $installer -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_pip=1" -Wait
    Remove-Item $installer -Force -ErrorAction SilentlyContinue
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

# 1. Python 3.12
if (-not (Test-Python)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Installing Python 3.12 via winget..."
        winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
        $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
        $env:Path = "$machinePath;$userPath"
    } else {
        Write-Host "winget not available (normal on Windows Server). Using python.org installer..."
        Install-Python312
    }
}

if (-not (Test-Python)) {
    Write-Host ""
    Write-Host "ERROR: Python still not found after install." -ForegroundColor Red
    Write-Host "Manual fix:" -ForegroundColor Yellow
    Write-Host "  1. Open Edge -> https://www.python.org/downloads/"
    Write-Host "  2. Download Python 3.12 for Windows"
    Write-Host "  3. Run installer -> CHECK 'Add python.exe to PATH' -> Install"
    Write-Host "  4. Close PowerShell, open NEW Administrator PowerShell"
    Write-Host "  5. cd C:\Users\Administrator\trading_bot"
    Write-Host "  6. Run .\setup_aws.ps1 again"
    exit 1
}

Write-Host "Python: $(python --version)" -ForegroundColor Green

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
