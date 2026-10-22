@echo off
REM Run a scan in this window. Add --telegram to also send it to Telegram, --backtest to re-test the rules.
cd /d "%~dp0"
".venv\Scripts\python.exe" run_scan.py %*
pause
