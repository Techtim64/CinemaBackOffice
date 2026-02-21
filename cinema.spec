# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.building.datastruct import Tree

hiddenimports = ['mysql.connector.plugins.caching_sha2_password']
hiddenimports += collect_submodules('mysql.connector.plugins')

datas = [
    ('assets/logo.png', 'assets'),
    ('assets/CinemaCentral.icns', 'assets'),
    Tree('icons', prefix='icons'),
    Tree('fonts', prefix='fonts'),
]

a = Analysis(
    ['cinema_main_menu.py'],
    pathex=[],
    binaries=[],
    datas=datas,
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
    upx=False,     # macOS: beter uit
    console=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='cinema',
)

app = BUNDLE(
    coll,
    name='Cinema.app',
    icon='assets/CinemaCentral.icns',
    bundle_identifier='be.cinema.backoffice',
    info_plist={
        'CFBundleShortVersionString': '1.0',
        'CFBundleVersion': '1',
        'CFBundleDisplayName': 'CinemaBackOffice',
        'NSHighResolutionCapable': True,
        'NSHumanReadableCopyright': '© 2026 Tim Caudron',
    },
)