@echo off
REM One-time setup on a new PC (already done on this one).
cd /d "%~dp0"
python -m venv .venv
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if not exist .env copy .env.example .env
if not exist holdings.csv copy holdings.example.csv holdings.csv
echo.
echo Setup finished. Open .env in Notepad and fill in your Fyers App ID, Secret and Redirect URL.
pause
