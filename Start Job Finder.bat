@echo off
rem One-click setup and launcher for the Job Finder web UI.
rem On the first run it creates a private environment and installs dependencies.
title Job Finder
cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    where python >nul 2>nul && set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo.
    echo  Job Finder needs Python 3.11 or newer.
    echo  Your browser will open the official Python download page.
    echo  Install Python, tick "Add python.exe to PATH", then run this file again.
    echo.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

echo.
echo  Preparing Job Finder... your browser will open when it is ready.
echo  The first start can take a few minutes while dependencies install.
echo.
echo  Keep this black window open while you use the app.
echo  When you're finished, just close this window.
echo.

%PYTHON_CMD% "scripts\bootstrap.py" --launch

if errorlevel 1 (
    echo.
    echo  Something went wrong. Read the message above, then see the
    echo  Troubleshooting section in README.md.
    echo.
    pause
)
