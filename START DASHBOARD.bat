@echo off
title Flo-Wing Dashboard - starter
cd /d "%~dp0"
echo.
echo  ===== Flo-Wing Operations Dashboard =====
echo.

rem --- find Python ---
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

rem --- checks ---
if not exist "backend\app\main.py" (
  echo  [X] Put this file inside the "flowing-dashboard" folder, next to "backend" and "frontend".
  pause & exit /b
)
if not exist "backend\service-account.json" (
  echo  [!] No key found at backend\service-account.json
  echo      The dashboard will open with DEMO data. To see your real sheets, copy your
  echo      JSON key into the "backend" folder, rename it to service-account.json, and run this again.
  echo.
)
where node >nul 2>nul
if errorlevel 1 (
  echo  [X] Node.js is not installed. Install the LTS version from nodejs.org, then run this again.
  start https://nodejs.org
  pause & exit /b
)
for /f "tokens=1 delims=v." %%a in ('node --version') do set NODEMAJOR=%%a
if %NODEMAJOR% LSS 20 (
  echo  [X] Your Node.js is too old. Install the LTS version from nodejs.org, then run this again.
  start https://nodejs.org
  pause & exit /b
)

rem --- stop an older copy that may still be running on the same ports ---
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do taskkill /PID %%p /F >nul 2>nul
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173 " ^| findstr LISTENING') do taskkill /PID %%p /F >nul 2>nul

echo  Starting the API (reads your Google Sheets)...
start "Flo-Wing API - keep open" cmd /k ""%PY%" -m pip install -q -r backend\requirements.txt && cd backend && "%PY%" -m uvicorn app.main:app --port 8000"

echo  Starting the dashboard website...
start "Flo-Wing WEBSITE - keep open" cmd /k "cd frontend && (if not exist node_modules npm.cmd install) && npm.cmd run dev"

echo.
echo  Waiting for both to start (the first time can take 2-3 minutes)...
timeout /t 25 /nobreak >nul
start http://localhost:5173
echo.
echo  Dashboard opened at http://localhost:5173
echo  Keep the two black windows open while you use it. Close them to stop.
echo.
pause
