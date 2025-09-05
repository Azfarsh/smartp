@echo off
echo ========================================
echo SmartPrint Vendor Client - Complete Setup
echo ========================================
echo.
echo This script will:
echo 1. Build the executable from Python source
echo 2. Install it to Desktop
echo 3. Set up automatic Windows startup
echo 4. Create shortcuts and configuration
echo.
echo The process may take several minutes.
echo.

REM Check if running as administrator
net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: This script requires administrator privileges
    echo Please right-click and "Run as administrator"
    pause
    exit /b 1
)

echo Starting complete setup process...
echo.

REM Step 1: Build the executable
echo ========================================
echo Step 1: Building executable...
echo ========================================
call build_executable.bat
if errorlevel 1 (
    echo ERROR: Build failed. Please check the build output above.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Step 2: Installing to Desktop...
echo ========================================
call install_to_desktop.bat
if errorlevel 1 (
    echo ERROR: Installation failed. Please check the installation output above.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Setup completed successfully!
echo ========================================
echo.
echo The SmartPrint Vendor Client is now:
echo - Installed on your Desktop
echo - Configured to start automatically with Windows
echo - Ready to process print jobs
echo.
echo You can:
echo - Use the desktop shortcut to run manually
echo - Check the application folder for logs
echo - Run uninstall.bat to remove everything
echo.
echo The service will start automatically on the next Windows boot.
echo.

REM Test the installation
echo Testing installation...
set "APP_FOLDER=%USERPROFILE%\Desktop\SmartPrintVendorClient"
if exist "%APP_FOLDER%\SmartPrintVendorClient.exe" (
    echo SUCCESS: Executable is installed
) else (
    echo ERROR: Executable not found after installation
)

set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if exist "%STARTUP_FOLDER%\SmartPrintVendorClient.vbs" (
    echo SUCCESS: Startup is configured
) else (
    echo ERROR: Startup not configured
)

echo.
echo Installation test completed.
echo.
echo Press any key to exit...
pause >nul
