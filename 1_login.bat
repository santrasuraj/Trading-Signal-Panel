@echo off
REM Log in to Fyers - do this once every trading morning.
cd /d "%~dp0"
".venv\Scripts\python.exe" login.py
pause
