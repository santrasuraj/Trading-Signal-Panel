# Creates Windows scheduled tasks that run the scan on weekdays and send the summary to Telegram:
#   15:40  right after the close (uses Fyers live prices if you logged in today)
#   19:15  after NSE publishes its official end-of-day files (final data)
# Run once:  right-click this file -> "Run with PowerShell"
# Remove later:  Unregister-ScheduledTask -TaskName "NSE Scanner*" -Confirm:$false

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"   # pythonw = no console window popping up
$days = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"

# Laptop friendly: run on battery, catch up after sleep, never hang for more than 20 minutes.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew

foreach ($t in @("15:40", "19:15")) {
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument "run_scan.py --telegram --by scheduled" `
        -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $t
    $name = "NSE Scanner $($t.Replace(':', ''))"
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force `
        -Description "NSE stock scanner - scan and Telegram summary" | Out-Null
    Write-Host "Created task: $name (weekdays at $t)"
}
Write-Host "`nDone. Log in to Fyers (1_login.bat) each trading day for real-time prices at 15:40."
Write-Host "Without login the scans still run (Yahoo for live prices, NSE official data in the evening)."
Write-Host "Problems are written to data\logs\scanner.log and sent to Telegram."
