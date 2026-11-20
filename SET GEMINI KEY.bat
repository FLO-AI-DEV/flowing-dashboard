@echo off
title Flo-Wing Assistant - Gemini key
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
if not exist "backend\set_gemini_key.py" (
  echo  [X] Put this file inside the "flowing-dashboard" folder, next to "backend" and "frontend".
  pause & exit /b
)
"%PY%" -m pip install -q requests >nul 2>nul
"%PY%" backend\set_gemini_key.py
