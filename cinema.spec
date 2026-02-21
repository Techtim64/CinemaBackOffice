# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['mysql.connector.plugins.caching_sha2_password']
hiddenimports += collect_submodules('mysql.connector.plugins')


a = Analysis(
    ['cinema.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/logo.png', 'assets')],
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='cinema',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='cinema',
)
app = BUNDLE(
    coll,
    name='Cinema.app',
    icon='assets/CinemaCentral.icns',   # <-- deze lijn
    bundle_identifier='be.cinema.backoffice',
    info_plist={
        'CFBundleShortVersionString': '1.0',
        'CFBundleVersion': '1',
        'CFBundleDisplayName': 'CinemaBackOffice',
        'NSHumanReadableCopyright': '© 2026 Tim Caudron',
        'NSHighResolutionCapable': True,
    },
)

