# Run MT5 micro-scalp bot on Windows AWS
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path ".env")) {
    Write-Host "Missing .env - run: copy .env.example .env  then edit it."
    exit 1
}

$venv = Join-Path $Root ".venv"
if (-not (Test-Path $venv)) {
    Write-Host "Missing .venv - run setup_aws.ps1 first."
    exit 1
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null

Write-Host "Starting MT5 bot... (MT5 terminal must be running)"
& "$venv\Scripts\python.exe" -u bot.py 2>&1 | Tee-Object -FilePath (Join-Path $Root "logs\live_run.log") -Append
