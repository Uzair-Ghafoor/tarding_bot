# Register bot to auto-start when Windows boots (runs at user logon)
# Requires: MT5 terminal set to auto-login, RDP session or always-on user

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunScript = Join-Path $Root "run_bot.ps1"
$TaskName = "ExnessMT5ScalpBot"

$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`""

$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Description "Exness MT5 micro-scalp bot" -Force

Write-Host "Scheduled task '$TaskName' created. It starts at Windows logon."
Write-Host "Ensure MT5 stays logged in and 'Algo Trading' is enabled."
