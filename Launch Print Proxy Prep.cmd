@echo off
setlocal

title Print Proxy Prep
cd /d "%~dp0"

if not exist "images" mkdir "images"
if not exist "images\crop" mkdir "images\crop"

if not exist "venv\Scripts\pythonw.exe" (
    echo The app is not set up yet.
    echo Running setup first...
    echo.
    call "%~dp0Setup Print Proxy Prep.cmd"
    if errorlevel 1 exit /b 1
)

start "" /b "venv\Scripts\pythonw.exe" "main.py"
exit /b 0
