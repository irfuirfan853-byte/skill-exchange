@echo off
title Skill Exchange - Demo Mode Launcher
cd /d "%~dp0"

echo ============================================
echo    Skill Exchange - Demo Mode Launcher
echo ============================================
echo.
echo Demo accounts will be created if the database is empty:
echo   demo1@skillexchange.com  /  demo1234
echo   demo2@skillexchange.com  /  demo1234
echo.

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    echo.
    echo Fix: open a terminal in this folder and run:
    echo   python -m venv venv
    echo   venv\Scripts\python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

venv\Scripts\python launch.py --demo

pause
