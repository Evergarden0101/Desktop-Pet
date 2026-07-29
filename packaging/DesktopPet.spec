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

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.getcwd())
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

block_cipher = None

# Bundle the character assets next to the executable.
datas = [
    (os.path.join(ROOT, "assets"), "assets"),
]

hiddenimports = collect_submodules("desktop_pet")

# MediaPipe powers photo import (finding a real person in the picture). It is
# optional: when it isn't installed at build time the exe simply falls back to
# silhouette analysis, so the build must not fail without it. Its graphs and
# .tflite models live in the package as data, which PyInstaller cannot infer.
binaries = []
try:
    import mediapipe  # noqa: F401

    datas += collect_data_files("mediapipe", include_py_files=True)
    binaries += collect_dynamic_libs("mediapipe")
    hiddenimports += collect_submodules("mediapipe.tasks")
    hiddenimports += ["mediapipe", "numpy"]
    print("[spec] bundling mediapipe for photo import")
except Exception as exc:  # pragma: no cover - build-time only
    print(f"[spec] mediapipe not available, photo import will use silhouette only ({exc})")

a = Analysis(
    # Absolute-import entry point (NOT desktop_pet/__main__.py, whose relative
    # import fails when PyInstaller runs it as the top-level __main__ script).
    [os.path.join(ROOT, "packaging", "app_entry.py")],
    pathex=[SRC],
    binaries=binaries,
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
