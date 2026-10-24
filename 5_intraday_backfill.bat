@echo off
REM One-time: ~1 year of 5-minute history from FYERS for the intraday strategies (~14 minutes).
REM Safe to stop and re-run - it continues where it stopped and never exceeds FYERS' rate limits.
cd /d "%~dp0"
REM This checkout's own venv, else the main checkout's (this folder may be a git worktree in .worktrees\), else PATH.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" if exist "..\..\.venv\Scripts\python.exe" set "PY=..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" intraday_sync.py --backfill --run
pause
