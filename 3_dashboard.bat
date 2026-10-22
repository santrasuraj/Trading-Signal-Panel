@echo off
REM Open the dashboard in your browser (http://localhost:8501). Keep this window open while using it.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless false --server.address 127.0.0.1 --browser.gatherUsageStats false
pause
