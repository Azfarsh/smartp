@echo off
echo ========================================
echo SmartPrint Vendor Client - Build Script
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python and try again
    pause
    exit /b 1
)

echo Python found. Checking dependencies...

REM Check if PyInstaller is installed
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo ERROR: Failed to install PyInstaller
        pause
        exit /b 1
    )
)

REM Check if required packages are installed
echo Checking required packages...
python -c "import PIL, win32print, requests, psutil" >nul 2>&1
if errorlevel 1 (
    echo Installing required packages...
    pip install Pillow pywin32 requests psutil
    if errorlevel 1 (
        echo ERROR: Failed to install required packages
        pause
        exit /b 1
    )
)

echo All dependencies are ready.
echo.

REM Create dist directory if it doesn't exist
if not exist "dist" mkdir dist

REM Clean previous builds
echo Cleaning previous builds...
if exist "dist\SmartPrintVendorClient.exe" del "dist\SmartPrintVendorClient.exe"
if exist "build" rmdir /s /q "build"

echo.
echo Building executable...
echo This may take a few minutes...
echo.

REM Build the executable using the spec file
pyinstaller --clean vendor_client.spec

if errorlevel 1 (
    echo.
    echo ERROR: Build failed!
    echo Check the error messages above for details.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Build completed successfully!
echo ========================================
echo.
echo Executable location: dist\SmartPrintVendorClient.exe
echo.

REM Check if the executable was created
if exist "dist\SmartPrintVendorClient.exe" (
    echo SUCCESS: SmartPrintVendorClient.exe has been created
    echo File size: 
    dir "dist\SmartPrintVendorClient.exe" | find "SmartPrintVendorClient.exe"
    echo.
    echo You can now run the installation script to:
    echo 1. Move the executable to Desktop
    echo 2. Set up automatic startup
    echo.
) else (
    echo ERROR: Executable was not created
    echo Check the build output above for errors
)

echo Press any key to exit...
pause >nul
