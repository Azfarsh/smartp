# SmartPrint Vendor Client - Executable Setup Guide

This guide will help you convert the SmartPrint Vendor Client into a Windows executable that runs automatically on startup.

## Overview

The setup process involves:
1. Building the Python script into a Windows executable (.exe)
2. Moving the executable to the Desktop
3. Setting up automatic startup when Windows boots
4. Creating shortcuts and configuration files

## Files Created

- `vendor_client.spec` - PyInstaller configuration file
- `build_executable.bat` - Script to build the executable
- `startup_launcher.bat` - Script that runs the executable on startup
- `install_to_desktop.bat` - Main installation script
- `uninstall.bat` - Uninstaller script

## Step-by-Step Instructions

### Step 1: Build the Executable

1. Open Command Prompt or PowerShell in the `smartprint` directory
2. Run the build script:
   ```cmd
   build_executable.bat
   ```
3. Wait for the build to complete (this may take several minutes)
4. The executable will be created in the `dist` folder

### Step 2: Install to Desktop and Setup Startup

1. **Right-click** on `install_to_desktop.bat` and select **"Run as administrator"**
2. The script will:
   - Copy the executable to Desktop
   - Create a startup entry in Windows
   - Create a desktop shortcut
   - Set up the print jobs directory
   - Create configuration files

### Step 3: Verify Installation

After installation, you should have:
- `SmartPrintVendorClient` folder on your Desktop
- Desktop shortcut: "SmartPrint Vendor Client"
- Automatic startup configured
- Print jobs directory: `C:\Users\[YourUsername]\Downloads\printjobs`

## How It Works

### Automatic Startup
- A VBS script is added to Windows startup folder
- This script runs `startup_launcher.bat` silently
- The launcher script runs the main executable
- All logging is preserved in the application folder

### Configuration
- Current settings from `vendor_client.py` are preserved
- Configuration is stored in `config.txt` in the application folder
- All printer mappings and API settings remain the same

### File Structure After Installation
```
Desktop/
└── SmartPrintVendorClient/
    ├── SmartPrintVendorClient.exe    # Main executable
    ├── startup_launcher.bat          # Startup script
    ├── startup_launcher.vbs          # Silent launcher
    ├── config.txt                    # Configuration
    ├── uninstall.bat                 # Uninstaller
    └── startup.log                   # Startup logs
```

## Manual Control

### Running Manually
- Double-click the desktop shortcut: "SmartPrint Vendor Client"
- Or navigate to the application folder and run `SmartPrintVendorClient.exe`

### Stopping the Service
- The executable runs in a console window
- Close the window to stop the service
- Or use Task Manager to end the process

### Viewing Logs
- Check `startup.log` in the application folder for startup issues
- The main executable creates its own log files in the print jobs directory

## Troubleshooting

### Build Issues
- Ensure Python is installed and in PATH
- Install required packages: `pip install pyinstaller Pillow pywin32 requests psutil`
- Check that all dependencies are available

### Startup Issues
- Verify the executable exists in the application folder
- Check Windows startup folder for the VBS script
- Review `startup.log` for error messages

### Runtime Issues
- Check the print jobs directory for activity logs
- Verify printer connections and names
- Ensure the Django server is running

## Uninstalling

### Automatic Uninstall
1. Navigate to the application folder on Desktop
2. Run `uninstall.bat` as administrator
3. Choose whether to keep print jobs directory

### Manual Uninstall
1. Remove from startup: Delete `SmartPrintVendorClient.vbs` from startup folder
2. Remove desktop shortcut: Delete "SmartPrint Vendor Client.lnk"
3. Remove application folder: Delete `SmartPrintVendorClient` folder from Desktop
4. (Optional) Remove print jobs directory

## Configuration Changes

To modify settings after installation:
1. Edit `config.txt` in the application folder
2. Or modify the source `vendor_client.py` and rebuild

## Security Notes

- The executable requires administrator privileges for installation
- The startup script runs with user privileges
- All network communications use the same security as the original script
- No additional security risks are introduced

## Support

If you encounter issues:
1. Check the log files in the application folder
2. Verify all dependencies are installed
3. Ensure the Django server is accessible
4. Check Windows Event Viewer for system errors

## File Locations

- **Application Folder**: `%USERPROFILE%\Desktop\SmartPrintVendorClient\`
- **Startup Entry**: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SmartPrintVendorClient.vbs`
- **Print Jobs**: `C:\Users\%USERNAME%\Downloads\printjobs\`
- **Logs**: Application folder and print jobs directory
