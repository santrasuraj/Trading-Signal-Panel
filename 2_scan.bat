@echo off
REM Run a scan in this window. Add --telegram to also send it to Telegram, --no-update to re-check without downloading.
cd /d "%~dp0"
REM This checkout's own venv, else the main checkout's (this folder may be a git worktree in .worktrees\), else PATH.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" if exist "..\..\.venv\Scripts\python.exe" set "PY=..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" run_scan.py %*
pause
