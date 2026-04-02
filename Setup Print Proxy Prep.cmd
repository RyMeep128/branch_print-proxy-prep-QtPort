@echo off
setlocal

title Print Proxy Prep Setup
cd /d "%~dp0"

echo.
echo ==================================
echo   Print Proxy Prep - Setup
echo ==================================
echo.

if not exist "images" (
    echo Creating images folder...
    mkdir "images"
)

if not exist "images\crop" (
    echo Creating crop output folder...
    mkdir "images\crop"
)

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher ^(`py`^) was not found.
    echo Please install Python from https://www.python.org/downloads/
    echo and enable "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -m venv venv
    if errorlevel 1 goto :setup_failed
) else (
    echo Virtual environment already exists.
)

echo Upgrading pip...
call "venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :setup_failed

echo Installing requirements...
call "venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :setup_failed

echo.
echo Setup complete.
echo You can now launch the app with:
echo   Launch Print Proxy Prep.cmd
echo.
pause
exit /b 0

:setup_failed
echo.
echo Setup did not finish successfully.
echo Please scroll up for the error details.
echo.
pause
exit /b 1
