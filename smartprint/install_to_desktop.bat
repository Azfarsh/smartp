@echo off
echo ========================================
echo SmartPrint Vendor Client - Installation
echo ========================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if errorlevel 1 (
    echo This script requires administrator privileges to set up startup.
    echo Please right-click and "Run as administrator"
    pause
    exit /b 1
)

REM Get current directory and desktop path
set "CURRENT_DIR=%~dp0"
set "DESKTOP_PATH=%USERPROFILE%\Desktop"
set "APP_FOLDER=%DESKTOP_PATH%\SmartPrintVendorClient"

echo Current directory: %CURRENT_DIR%
echo Desktop path: %DESKTOP_PATH%
echo App folder: %APP_FOLDER%
echo.

REM Check if executable exists
if not exist "%CURRENT_DIR%dist\SmartPrintVendorClient.exe" (
    echo ERROR: SmartPrintVendorClient.exe not found in dist folder
    echo Please run build_executable.bat first to create the executable
    pause
    exit /b 1
)

echo Step 1: Creating application folder on desktop...
if exist "%APP_FOLDER%" (
    echo Removing existing installation...
    rmdir /s /q "%APP_FOLDER%"
)
mkdir "%APP_FOLDER%"

echo Step 2: Copying files to desktop...
copy "%CURRENT_DIR%dist\SmartPrintVendorClient.exe" "%APP_FOLDER%\"
copy "%CURRENT_DIR%startup_launcher.bat" "%APP_FOLDER%\"

REM Create a configuration file with current settings
echo Step 3: Creating configuration file...
(
echo # SmartPrint Vendor Client Configuration
echo # This file contains the current settings from vendor_client.py
echo.
echo VENDOR_EMAIL=azfarshaikh7860@gmail.com
echo VENDOR_NAME=azfarxerox
echo VENDOR_ID=9080823634
echo VENDOR_TOKEN=1498760458
echo BASE_URL=http://localhost:8000
echo LOCAL_JOB_DIR=C:\Users\%USERNAME%\Downloads\printjobs
echo POLL_INTERVAL=10
echo CLEANUP_INTERVAL=3600
echo JOB_RETENTION_HOURS=3
echo.
echo # Printer settings
echo PRIMARY_PRINTER=Canon GX2000 series
echo SERVICE_PRINTERS=regular print:HPFA7489 (HP LaserJet Pro MFP 4104),photo_print:Canon GX2000 series,passport_photo:Canon GX2000 series
) > "%APP_FOLDER%\config.txt"

echo Step 4: Setting up Windows startup...
REM Create a VBS script to run the launcher silently
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.Run chr^(34^) ^& "%APP_FOLDER%\startup_launcher.bat" ^& chr^(34^), 0, False
) > "%APP_FOLDER%\startup_launcher.vbs"

REM Add to Windows startup folder
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
copy "%APP_FOLDER%\startup_launcher.vbs" "%STARTUP_FOLDER%\SmartPrintVendorClient.vbs"

echo Step 5: Creating desktop shortcut...
REM Create a desktop shortcut for manual control
(
echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
echo sLinkFile = "%DESKTOP_PATH%\SmartPrint Vendor Client.lnk"
echo Set oLink = oWS.CreateShortcut^(sLinkFile^)
echo oLink.TargetPath = "%APP_FOLDER%\SmartPrintVendorClient.exe"
echo oLink.WorkingDirectory = "%APP_FOLDER%"
echo oLink.Description = "SmartPrint Vendor Client - Manual Control"
echo oLink.Save
) > "%TEMP%\create_shortcut.vbs"
cscript //nologo "%TEMP%\create_shortcut.vbs"
del "%TEMP%\create_shortcut.vbs"

echo Step 6: Creating uninstall script...
(
echo @echo off
echo echo Uninstalling SmartPrint Vendor Client...
echo.
echo REM Remove from startup
echo if exist "%STARTUP_FOLDER%\SmartPrintVendorClient.vbs" del "%STARTUP_FOLDER%\SmartPrintVendorClient.vbs"
echo.
echo REM Remove desktop shortcut
echo if exist "%DESKTOP_PATH%\SmartPrint Vendor Client.lnk" del "%DESKTOP_PATH%\SmartPrint Vendor Client.lnk"
echo.
echo REM Remove application folder
echo if exist "%APP_FOLDER%" rmdir /s /q "%APP_FOLDER%"
echo.
echo echo SmartPrint Vendor Client has been uninstalled.
echo pause
) > "%APP_FOLDER%\uninstall.bat"

echo Step 7: Creating print jobs directory...
set "PRINT_JOBS_DIR=C:\Users\%USERNAME%\Downloads\printjobs"
if not exist "%PRINT_JOBS_DIR%" mkdir "%PRINT_JOBS_DIR%"
if not exist "%PRINT_JOBS_DIR%\failed_jobs" mkdir "%PRINT_JOBS_DIR%\failed_jobs"
if not exist "%PRINT_JOBS_DIR%\vendor_jobs" mkdir "%PRINT_JOBS_DIR%\vendor_jobs"

echo.
echo ========================================
echo Installation completed successfully!
echo ========================================
echo.
echo Files installed to: %APP_FOLDER%
echo Startup configured: Yes
echo Desktop shortcut created: Yes
echo Print jobs directory: %PRINT_JOBS_DIR%
echo.
echo The SmartPrint Vendor Client will now start automatically when Windows boots.
echo You can also run it manually using the desktop shortcut.
echo.
echo To uninstall, run: %APP_FOLDER%\uninstall.bat
echo.

REM Test the installation
echo Testing installation...
if exist "%APP_FOLDER%\SmartPrintVendorClient.exe" (
    echo SUCCESS: Executable is in place
) else (
    echo ERROR: Executable not found after installation
)

if exist "%STARTUP_FOLDER%\SmartPrintVendorClient.vbs" (
    echo SUCCESS: Startup script is configured
) else (
    echo ERROR: Startup script not configured
)

if exist "%DESKTOP_PATH%\SmartPrint Vendor Client.lnk" (
    echo SUCCESS: Desktop shortcut created
) else (
    echo ERROR: Desktop shortcut not created
)

echo.
echo Installation test completed.
echo.
echo Press any key to exit...
pause >nul
