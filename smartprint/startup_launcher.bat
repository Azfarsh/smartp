@echo off
REM SmartPrint Vendor Client - Startup Launcher
REM This script runs the vendor client executable and handles errors gracefully

REM Set the path to the executable (will be updated during installation)
set "EXECUTABLE_PATH=%~dp0SmartPrintVendorClient.exe"

REM Check if the executable exists
if not exist "%EXECUTABLE_PATH%" (
    echo SmartPrint Vendor Client executable not found at: %EXECUTABLE_PATH%
    echo Please run the installation script again.
    timeout /t 5 /nobreak >nul
    exit /b 1
)

REM Create a log file for startup issues
set "LOG_FILE=%~dp0startup.log"
echo [%date% %time%] Starting SmartPrint Vendor Client >> "%LOG_FILE%"

REM Run the executable
echo Starting SmartPrint Vendor Client...
"%EXECUTABLE_PATH%"

REM Check if the executable exited with an error
if errorlevel 1 (
    echo [%date% %time%] SmartPrint Vendor Client exited with error code: %errorlevel% >> "%LOG_FILE%"
    echo SmartPrint Vendor Client encountered an error and stopped.
    echo Check the startup.log file for details.
    timeout /t 10 /nobreak >nul
) else (
    echo [%date% %time%] SmartPrint Vendor Client stopped normally >> "%LOG_FILE%"
)

REM Keep the window open briefly to show any error messages
timeout /t 3 /nobreak >nul
