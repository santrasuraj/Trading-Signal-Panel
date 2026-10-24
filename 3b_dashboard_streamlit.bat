@echo off
REM The old Streamlit dashboard (http://localhost:8501), kept until Quant Desk passes its acceptance list. Keep this window open while using it.
cd /d "%~dp0"
REM This checkout's own venv, else the main checkout's (this folder may be a git worktree in .worktrees\), else PATH.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" if exist "..\..\.venv\Scripts\python.exe" set "PY=..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m streamlit run app.py --server.headless false --server.address 127.0.0.1 --browser.gatherUsageStats false
pause
