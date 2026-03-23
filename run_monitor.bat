@echo off
REM Windows batch file to run the monitoring script

REM Get the directory where this script is located
cd /d "%~dp0"

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed or not in PATH
    echo Please install Python 3.8+ and add it to PATH
    pause
    exit /b 1
)

REM Check if requirements are installed
python -c "import selenium" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing required packages...
    pip install -r requirements.txt
)

REM Run the monitor
echo Starting HetrixTools Monitor...
python monitor.py

pause
