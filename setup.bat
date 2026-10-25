@echo off
REM One-time setup on a new PC (already done on this one).
cd /d "%~dp0"
REM Python 3.12 (the version the pinned libraries are tested with) through the py launcher, else "python" on PATH.
py -3.12 -m venv .venv 2>nul || python -m venv .venv
if not exist ".venv\Scripts\python.exe" (echo Creating .venv failed - install Python 3.12 and run this again. & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo Installing the libraries failed - see the messages above. & pause & exit /b 1)
if not exist .env copy .env.example .env
if not exist holdings.csv copy holdings.example.csv holdings.csv
echo.
echo Setup finished. Open .env in Notepad and fill in your Fyers App ID, Secret and Redirect URL.
pause
