# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['vendor_client.py'],
    pathex=[],
    binaries=[],
    datas=[('settings.py', 'smartprint')],
    hiddenimports=['django', 'django.conf', 'django.conf.settings', 'boto3', 'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont', 'PIL.ImageWin', 'win32print', 'win32api', 'win32ui', 'win32con', 'win32gui', 'requests', 'psutil', 'urllib3', 'concurrent.futures', 'http.server', 'socketserver'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VendorClient',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
