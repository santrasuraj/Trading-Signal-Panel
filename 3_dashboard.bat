@echo off
REM Open Quant Desk at http://127.0.0.1:8600. Keep this window open while using it.
REM (The old Streamlit dashboard is still available: 3b_dashboard_streamlit.bat)
cd /d "%~dp0"

REM Build the app when there is no Quant Desk build yet (no web\ui\dist, or the old Vite template page)
REM or when a UI file is newer than the build (after a git pull or an edit).
set "HAVE_BUILD="
set "NEED_BUILD="
findstr /c:"Quant Desk" "web\ui\dist\index.html" >nul 2>nul && set "HAVE_BUILD=1"
if not defined HAVE_BUILD set "NEED_BUILD=1"
powershell -NoProfile -Command "$f = @(Get-ChildItem 'web\ui' -File) + @(Get-ChildItem 'web\ui\src','web\ui\public' -Recurse -File -ErrorAction SilentlyContinue); $new = $f | Sort-Object LastWriteTimeUtc | Select-Object -Last 1; $d = Get-Item 'web\ui\dist\index.html' -ErrorAction SilentlyContinue; if (-not $d -or ($new -and $new.LastWriteTimeUtc -gt $d.LastWriteTimeUtc)) { exit 1 }" || set "NEED_BUILD=1"

REM npm ci only when node_modules is missing or older than package-lock.json (it deletes and reinstalls everything)
set "NEED_CI="
if not exist "web\ui\node_modules\.package-lock.json" set "NEED_CI=1"
powershell -NoProfile -Command "$l = Get-Item 'web\ui\package-lock.json' -ErrorAction SilentlyContinue; $m = Get-Item 'web\ui\node_modules\.package-lock.json' -ErrorAction SilentlyContinue; if ($l -and $m -and $l.LastWriteTimeUtc -gt $m.LastWriteTimeUtc) { exit 1 }" || set "NEED_CI=1"

set "NO_NPM="
if defined NEED_BUILD (
  where npm >nul 2>nul || set "NO_NPM=1"
)
if defined NO_NPM if defined HAVE_BUILD (
  echo Node.js was not found, so the app cannot be rebuilt - starting the existing build, which may be out of date.
  set "NEED_BUILD="
)
if defined NO_NPM if defined NEED_BUILD (
  echo Node.js is needed once to build the app: install it from https://nodejs.org and run this again.
  pause
  exit /b 1
)
if defined NEED_BUILD (
  echo Building the app - about a minute...
  pushd web\ui
  if defined NEED_CI (
    call npm ci || (popd & echo npm ci failed - see the messages above. & pause & exit /b 1)
  )
  call npm run build || (popd & echo The build failed - see the messages above. & pause & exit /b 1)
  popd
)

REM This checkout's own venv, else the main checkout's (this folder may be a git worktree in .worktrees\), else PATH.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" if exist "..\..\.venv\Scripts\python.exe" set "PY=..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m web.serve
pause
