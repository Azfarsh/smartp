@echo off
echo ========================================
echo SmartPrint Vendor Client - Uninstaller
echo ========================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if errorlevel 1 (
    echo This script requires administrator privileges to remove startup entries.
    echo Please right-click and "Run as administrator"
    pause
    exit /b 1
)

echo This will completely remove SmartPrint Vendor Client from your system.
echo.
echo The following will be removed:
echo - Application files from Desktop
echo - Windows startup entry
echo - Desktop shortcut
echo - Print jobs directory (optional)
echo.

set /p "REMOVE_JOBS=Do you want to remove the print jobs directory? (y/N): "
if /i "%REMOVE_JOBS%"=="y" (
    set "REMOVE_JOBS_DIR=yes"
) else (
    set "REMOVE_JOBS_DIR=no"
)

echo.
echo Starting uninstallation...

REM Define paths
set "DESKTOP_PATH=%USERPROFILE%\Desktop"
set "APP_FOLDER=%DESKTOP_PATH%\SmartPrintVendorClient"
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "PRINT_JOBS_DIR=C:\Users\%USERNAME%\Downloads\printjobs"

echo Step 1: Removing Windows startup entry...
if exist "%STARTUP_FOLDER%\SmartPrintVendorClient.vbs" (
    del "%STARTUP_FOLDER%\SmartPrintVendorClient.vbs"
    echo SUCCESS: Startup entry removed
) else (
    echo INFO: Startup entry not found
)

echo Step 2: Removing desktop shortcut...
if exist "%DESKTOP_PATH%\SmartPrint Vendor Client.lnk" (
    del "%DESKTOP_PATH%\SmartPrint Vendor Client.lnk"
    echo SUCCESS: Desktop shortcut removed
) else (
    echo INFO: Desktop shortcut not found
)

echo Step 3: Removing application folder...
if exist "%APP_FOLDER%" (
    rmdir /s /q "%APP_FOLDER%"
    echo SUCCESS: Application folder removed
) else (
    echo INFO: Application folder not found
)

if "%REMOVE_JOBS_DIR%"=="yes" (
    echo Step 4: Removing print jobs directory...
    if exist "%PRINT_JOBS_DIR%" (
        rmdir /s /q "%PRINT_JOBS_DIR%"
        echo SUCCESS: Print jobs directory removed
    ) else (
        echo INFO: Print jobs directory not found
    )
) else (
    echo Step 4: Keeping print jobs directory...
    echo INFO: Print jobs directory preserved at: %PRINT_JOBS_DIR%
)

echo.
echo ========================================
echo Uninstallation completed!
echo ========================================
echo.
echo SmartPrint Vendor Client has been completely removed from your system.
if "%REMOVE_JOBS_DIR%"=="no" (
    echo.
    echo Note: Print jobs directory was preserved at: %PRINT_JOBS_DIR%
    echo You can manually delete it if no longer needed.
)
echo.
echo Press any key to exit...
pause >nul
