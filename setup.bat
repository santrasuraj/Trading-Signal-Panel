@echo off
REM One-time setup (already done on this PC). Use on a new PC or if the .venv folder gets deleted.
cd /d "%~dp0"
python -m venv .venv
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Setup finished. Now open .env in Notepad and fill in your Fyers App ID and Secret.
pause
