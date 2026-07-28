# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for building DesktopPet.exe.

Build (on Windows):

    pip install -r requirements.txt pyinstaller
    pyinstaller packaging/DesktopPet.spec

The result is a single-folder app under ``dist/DesktopPet`` and, because
``onefile`` is enabled below, a standalone ``dist/DesktopPet.exe``.
"""

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.getcwd())
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

block_cipher = None

# Bundle the character assets next to the executable.
datas = [
    (os.path.join(ROOT, "assets"), "assets"),
]

hiddenimports = collect_submodules("desktop_pet")

a = Analysis(
    [os.path.join(SRC, "desktop_pet", "__main__.py")],
    pathex=[SRC],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Trim large, unused Qt modules to keep the exe smaller.
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.Qt3DCore",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="DesktopPet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app: no console window
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "packaging", "app.ico")
    if os.path.exists(os.path.join(ROOT, "packaging", "app.ico"))
    else None,
)
