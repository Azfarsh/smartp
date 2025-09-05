# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

# Get the current directory
import os
current_dir = os.path.dirname(os.path.abspath(SPEC))

# Define the main script
main_script = os.path.join(current_dir, 'vendor_client.py')

# Hidden imports that PyInstaller might miss
hidden_imports = [
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.ImageWin',
    'win32print',
    'win32api',
    'win32ui',
    'win32con',
    'win32gui',
    'psutil',
    'requests',
    'json',
    'threading',
    'subprocess',
    'tempfile',
    'signal',
    'asyncio',
    'concurrent.futures',
    'queue',
    'logging',
    'glob',
    'pathlib',
    'math',
    'collections',
    'dataclasses',
    'urllib.parse',
    'datetime',
    'io',
    'platform',
    'time',
    'os',
    'sys',
    'argparse'
]

# Data files to include (if any)
datas = []

# Binaries to include (if any)
binaries = []

# Analysis
a = Analysis(
    [main_script],
    pathex=[current_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# Remove duplicate files
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# Create executable
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SmartPrintVendorClient',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Keep console for logging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # You can add an icon file here if you have one
    version=None,  # You can add a version file here if you have one
)
