# Creates two Windows scheduled tasks that run the scan on weekdays and send it to Telegram:
#   09:45  (after the opening volatility settles)
#   15:05  (before the close - time to act on end-of-day signals)
# Run once:  right-click this file -> "Run with PowerShell"
# Remove later:  Unregister-ScheduledTask -TaskName "NSE Scanner*" -Confirm:$false

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$days = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"

foreach ($t in @("09:45", "15:05")) {
    $action = New-ScheduledTaskAction -Execute $python -Argument "run_scan.py --telegram" -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $t
    $name = "NSE Scanner $($t.Replace(':', ''))"
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Force `
        -Description "NSE stock scanner - scan and Telegram summary" | Out-Null
    Write-Host "Created task: $name (weekdays at $t)"
}
Write-Host "`nDone. Remember: log in to Fyers (1_login.bat) each morning before 09:45 for live data."
Write-Host "Without login, the scheduled scan still runs using delayed Yahoo data."
