# Creates Windows scheduled tasks that run the scan on weekdays and send the summary to Telegram:
#   08:30  before the open (yesterday's official NSE data, final signals) - a second chance on days NSE's
#          file came out after 19:15; it finishes well before the 09:14 intraday task
#   15:40  right after the close (uses Fyers live prices if you logged in today)
#   19:15  after NSE publishes its official end-of-day files (final data)
# Run once:  right-click this file -> "Run with PowerShell"
# Remove later:  Unregister-ScheduledTask -TaskName "NSE Scanner*" -Confirm:$false

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
# The task names below are fixed and registered with -Force. From a git worktree (.worktrees\<branch>) they would
# silently replace the main checkout's tasks and run THIS branch's scanner on the shared data folder every weekday.
if ($root -match '\\\.worktrees\\') {
    Write-Host "This copy is a git worktree ($root)."
    Write-Host "Scheduled tasks would replace the main checkout's tasks (same names) and run this branch on the shared data."
    $answer = Read-Host "Type YES to register the tasks from this worktree anyway"
    if ($answer -ne "YES") {
        Write-Host "Nothing was changed. Run setup_schedule.ps1 from the main checkout instead."
        exit 1
    }
}
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"   # pythonw = no console window popping up
# This checkout's own venv, else the main checkout's (this folder may be a git worktree in .worktrees\)
if (-not (Test-Path $pythonw)) { $pythonw = Join-Path $root "..\..\.venv\Scripts\pythonw.exe" }
if (-not (Test-Path $pythonw)) {
    Write-Host "Python was not found in .venv - run setup.bat first, then this file again."
    exit 1
}
$pythonw = (Resolve-Path $pythonw).Path
$days = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"

# Laptop friendly: run on battery, catch up after sleep, never hang for more than 45 minutes (a first run after
# an update re-downloads and repairs the history and re-tests every strategy; a task killed at the limit sends
# no Telegram message, so the limit is generous).
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -MultipleInstances IgnoreNew

foreach ($t in @("08:30", "15:40", "19:15")) {
    # --status: the dashboards (Quant Desk and the old Streamlit app) follow a scheduled scan's progress and see
    # whether it failed, from the same status file their own scans write
    $action = New-ScheduledTaskAction -Execute $pythonw `
        -Argument "run_scan.py --telegram --by scheduled --status data\results\status.json" -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $t
    $name = "NSE Scanner $($t.Replace(':', ''))"
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force `
        -Description "NSE stock scanner - scan and Telegram summary" | Out-Null
    Write-Host "Created task: $name (weekdays at $t)"
}

# 09:45-15:15 every 30 minutes: a live scan on today's forming candle (FYERS real time when logged in, else Yahoo
# ~15 min delayed). Its signals are provisional (what each strategy would do if the market closed now) and are
# never journaled; the 15:40 / 19:15 scans give the final ones. No Telegram: one summary per scheduled scan above.
$liveScan = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 25) -MultipleInstances IgnoreNew
$action = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "run_scan.py --live-only --by live --status data\results\status.json" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At "09:45"
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At "09:45" -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Hours 5 -Minutes 31)).Repetition
Register-ScheduledTask -TaskName "NSE Scanner live" -Action $action -Trigger $trigger -Settings $liveScan -Force `
    -Description "NSE stock scanner - live scan in market hours (provisional signals)" | Out-Null
Write-Host "Created task: NSE Scanner live (weekdays 09:45-15:15, every 30 minutes)"

# Intraday (FYERS first, inside the shared rate limiter):
#   09:14  live 5-minute bars from the FYERS WebSocket until 15:31 (no REST calls; if today's login is
#          missing it waits for it - log in with 1_login.bat - and on weekends/NSE holidays it just exits)
#   15:45  archive today's bars from FYERS (~150 calls) and re-test the intraday strategies
#   Their output goes to data\logs\intraday.log.
$liveSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 7) -MultipleInstances IgnoreNew
$jobs = @(
    @{ Time = "09:14"; Args = "intraday_sync.py --live"; Name = "NSE Scanner intraday live"; Settings = $liveSettings },
    @{ Time = "15:45"; Args = "intraday_sync.py --archive --run"; Name = "NSE Scanner intraday archive"; Settings = $settings }
)
foreach ($j in $jobs) {
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument $j.Args -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $j.Time
    Register-ScheduledTask -TaskName $j.Name -Action $action -Trigger $trigger -Settings $j.Settings -Force `
        -Description "NSE stock scanner - intraday data (FYERS)" | Out-Null
    Write-Host "Created task: $($j.Name) (weekdays at $($j.Time))"
}

#   09:20-15:05 every 5 minutes: live intraday signals, only from strategies whose backtest shows a real edge
#   after costs (no FYERS history calls; when none is proven it only writes that note and exits)
$sigSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "intraday_sync.py --signals" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At "09:20"
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At "09:20" -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Hours 5 -Minutes 45)).Repetition
Register-ScheduledTask -TaskName "NSE Scanner intraday signals" -Action $action -Trigger $trigger -Settings $sigSettings `
    -Force -Description "NSE stock scanner - live intraday signals from proven strategies" | Out-Null
Write-Host "Created task: NSE Scanner intraday signals (weekdays 09:20-15:05, every 5 minutes)"
Write-Host "`nDone. Log in to Fyers (1_login.bat) each trading day before 09:14 for real-time prices."
Write-Host "Without login the scans still run (Yahoo for live prices, NSE official data in the evening)."
Write-Host "Problems are written to data\logs\scanner.log and sent to Telegram (intraday jobs: data\logs\intraday.log)."
