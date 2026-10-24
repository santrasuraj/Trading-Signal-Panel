@echo off
REM One-time build of the survivorship-free backtest universe (downloads ~2,000 NSE day files and
REM corporate-action notices, ~20-30 minutes). Scans keep it up to date afterwards.
REM Add "compare" to print current-list vs point-in-time results instead.
cd /d "%~dp0"
if "%1"=="" (".venv\Scripts\python.exe" -u -m scanner.pit build) else (".venv\Scripts\python.exe" -u -m scanner.pit %*)
pause
