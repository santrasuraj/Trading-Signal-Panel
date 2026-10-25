@echo off
REM One-time build of the survivorship-free backtest universe (downloads ~2,000 NSE day files and
REM corporate-action notices, ~20-30 minutes). Scans keep it up to date afterwards.
REM Add "compare" to print current-list vs point-in-time results instead.
REM Don't run a scan (dashboard or scheduled) while this runs: both rebuild the same files.
cd /d "%~dp0"
REM This checkout's own venv, else the main checkout's (this folder may be a git worktree in .worktrees\), else PATH.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" if exist "..\..\.venv\Scripts\python.exe" set "PY=..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
if "%~1"=="" ("%PY%" -u -m scanner.pit build) else ("%PY%" -u -m scanner.pit %*)
pause
