# Run MT5 micro-scalp bot on Windows AWS (Task Scheduler or RDP session)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path ".env")) {
    Write-Host "Copy .env.example to .env and fill in demo credentials."
    exit 1
}

$venv = Join-Path $Root ".venv"
if (-not (Test-Path $venv)) {
    python -m venv $venv
    & "$venv\Scripts\pip.exe" install -r requirements.txt
}

$logDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

Write-Host "Starting MT5 bot… (MT5 terminal must be running)"
& "$venv\Scripts\python.exe" -u bot.py 2>&1 | Tee-Object -FilePath (Join-Path $logDir "live_run.log") -Append
