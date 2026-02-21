# -*- mode: python ; coding: utf-8 -*-
import os

BASE_DIR = SPECPATH

def add_file(rel_path, dest_dir):
    src = os.path.join(BASE_DIR, rel_path)
    if not os.path.isfile(src):
        print(f"[WARN] missing file: {src}")
        return
    DATAS.append((src, dest_dir))

def add_folder(rel_folder):
    folder = os.path.join(BASE_DIR, rel_folder)
    if not os.path.isdir(folder):
        print(f"[WARN] missing folder: {folder}")
        return
    for root, _dirs, files in os.walk(folder):
        for fn in files:
            src = os.path.join(root, fn)
            dest = os.path.relpath(root, BASE_DIR)   # bv icons/ui
            DATAS.append((src, dest))

# ✅ bouw datas in aparte lijst
DATAS = []
add_file("assets/logo.png", "assets")
add_file("assets/CinemaCentral.icns", "assets")
add_folder("icons")
add_folder("fonts")

# ✅ harde check: elk datas item moet EXACT (src, dest) zijn
for i, item in enumerate(DATAS):
    if not (isinstance(item, tuple) and len(item) == 2):
        raise SystemExit(f"[FATAL] datas[{i}] is not a (src,dest) tuple: {repr(item)}")

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['mysql.connector.plugins.caching_sha2_password']
hiddenimports += collect_submodules('mysql.connector.plugins')

a = Analysis(
    [os.path.join(BASE_DIR, 'cinema_main_menu.py')],
    pathex=[BASE_DIR],
    binaries=[],
    datas=DATAS,
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
    upx=False,
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
    icon=os.path.join(BASE_DIR, 'assets', 'CinemaCentral.icns'),
    bundle_identifier='be.cinema.backoffice',
    info_plist={
        'CFBundleShortVersionString': '1.0',
        'CFBundleVersion': '1',
        'CFBundleDisplayName': 'CinemaBackOffice',
        'NSHighResolutionCapable': True,
        'NSHumanReadableCopyright': '© 2026 Tim Caudron',
    },
)