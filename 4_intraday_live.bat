@echo off
REM Real-time 5-minute bars from the FYERS WebSocket (no API calls used) until 15:31.
REM Log in first (1_login.bat) - if you forget, it waits for the login. Started early, it waits for the open.
REM Keep this window open during market hours. Only one live feed runs at a time.
cd /d "%~dp0"
REM This checkout's own venv, else the main checkout's (this folder may be a git worktree in .worktrees\), else PATH.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" if exist "..\..\.venv\Scripts\python.exe" set "PY=..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" intraday_sync.py --live
pause
