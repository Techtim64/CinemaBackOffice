# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules

BASE_DIR = SPECPATH

def add_file(rel_path, dest_dir):
    src = os.path.join(BASE_DIR, rel_path)
    if os.path.isfile(src):
        DATAS.append((src, dest_dir))
    else:
        print(f"[WARN] missing file: {src}")

def add_folder(rel_folder):
    folder = os.path.join(BASE_DIR, rel_folder)
    if not os.path.isdir(folder):
        print(f"[WARN] missing folder: {folder}")
        return
    for root, _dirs, files in os.walk(folder):
        for fn in files:
            src = os.path.join(root, fn)
            dest = os.path.relpath(root, BASE_DIR)  # icons/ui, fonts, ...
            DATAS.append((src, dest))

hiddenimports = ['mysql.connector.plugins.caching_sha2_password']
hiddenimports += collect_submodules('mysql.connector.plugins')

DATAS = []
add_file("assets/logo.png", "assets")
add_folder("icons")
add_folder("fonts")

# Windows icon (ICO!)
WIN_ICON = os.path.join(BASE_DIR, "assets", "CinemaCentral.ico")

a = Analysis(
    [os.path.join(BASE_DIR, "cinema_main_menu.py")],
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
    name="CinemaBackOffice",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=WIN_ICON if os.path.isfile(WIN_ICON) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CinemaBackOffice",
)