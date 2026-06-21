# PowerShell script to register the local MX relay scheduled task on Windows
# Run this script as Administrator or from your user shell to schedule relay_push.cmd every 5 minutes.

$ScriptPath = "C:\Users\DANNY\Desktop\treasuryforge\scripts\relay_push.cmd"

if (-not (Test-Path $ScriptPath)) {
    Write-Error "Could not find relay_push.cmd at $ScriptPath"
    exit 1
}

$Action = New-ScheduledTaskAction -Execute $ScriptPath
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 9999)
$LogonTrigger = New-ScheduledTaskTrigger -AtLogon
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

try {
    Register-ScheduledTask -TaskName "TreasuryForgeRelay" -Action $Action -Trigger @($Trigger, $LogonTrigger) -Settings $Settings -Description "TreasuryForge Local MX Relay Task to fetch and push Binance/Bybit funding rates to the Netcup VPS every 5 minutes." -Force
    Write-Host "Scheduled task 'TreasuryForgeRelay' successfully registered!"
    Write-Host "It is configured to run every 5 minutes and automatically start at user logon."
} catch {
    Write-Error "Failed to register scheduled task. If you receive permission errors, try running PowerShell as Administrator."
    exit 1
}
