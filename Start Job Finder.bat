@echo off
rem One-click launcher for the Job Finder web UI.
rem Double-click this file (or a desktop shortcut to it) - no terminal needed.
rem It starts the local web app and opens it in the browser.
title Job Finder
cd /d "%~dp0"

rem Prefer the project's virtual environment if it exists; otherwise fall
rem back to the Python on PATH.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo  Starting Job Finder... your browser will open in a moment.
echo.
echo  Keep this black window open while you use the app.
echo  When you're finished, just close this window.
echo.

"%PY%" "scripts\run_ui.py"

if errorlevel 1 (
    echo.
    echo  Something went wrong starting the app. Show this window to
    echo  whoever installed it for you.
    echo.
    pause
)
