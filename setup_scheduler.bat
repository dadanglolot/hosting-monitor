@echo off
REM Setup script for Windows Task Scheduler

setlocal enabledelayedexpansion

REM Get current directory
set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

echo.
echo ========================================
echo HetrixTools Monitor - Task Scheduler Setup
echo ========================================
echo.
echo This script will set up automatic monitoring using Windows Task Scheduler.
echo.

REM Ask for schedule frequency
echo Select monitoring frequency:
echo 1) Every hour
echo 2) Every 30 minutes
echo 3) Every 15 minutes
echo 4) Every 5 minutes
echo 5) Custom (enter your own)
echo.

set /p choice="Enter choice (1-5): "

if "%choice%"=="1" (
    set INTERVAL=PT1H
    set INTERVAL_DESC=1 hour
) else if "%choice%"=="2" (
    set INTERVAL=PT30M
    set INTERVAL_DESC=30 minutes
) else if "%choice%"=="3" (
    set INTERVAL=PT15M
    set INTERVAL_DESC=15 minutes
) else if "%choice%"=="4" (
    set INTERVAL=PT5M
    set INTERVAL_DESC=5 minutes
) else if "%choice%"=="5" (
    set /p INTERVAL="Enter interval (e.g., PT30M for 30 minutes, PT2H for 2 hours): "
    set INTERVAL_DESC=!INTERVAL!
) else (
    echo Invalid choice. Using 1 hour as default.
    set INTERVAL=PT1H
    set INTERVAL_DESC=1 hour
)

REM Create the task
echo.
echo Creating scheduled task...
echo Task name: HetrixTools-Monitor
echo Location: !SCRIPT_DIR!
echo Interval: !INTERVAL_DESC!
echo.

schtasks /create /tn "HetrixTools-Monitor" /tr "python.exe \"%SCRIPT_DIR%\monitor.py\"" /sc onidle /f 2>nul

if %errorlevel% equ 0 (
    echo.
    echo SUCCESS! Task created.
    echo.
    echo The monitor will run every !INTERVAL_DESC!
    echo.
    echo View task details:
    echo   - Open Task Scheduler
    echo   - Look for "HetrixTools-Monitor" in the task list
    echo.
    echo To remove the task later, run:
    echo   schtasks /delete /tn "HetrixTools-Monitor" /f
    echo.
) else (
    echo.
    echo FAILED! Could not create task.
    echo Make sure you're running this as Administrator.
    echo.
)

pause
