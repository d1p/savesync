# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SaveSync-Bridge.

Build command:
    uv run build-exe          # uses scripts/build_exe.py
    # or directly:
    uv run pyinstaller savesync_bridge.spec --noconfirm
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(SPECPATH)  # noqa: F821  (PyInstaller injects SPECPATH)
SRC  = ROOT / "src" / "savesync_bridge"

# --------------------------------------------------------------------------
# Binaries bundled with the app
# --------------------------------------------------------------------------
platform_dir = "windows" if sys.platform == "win32" else "linux"
bin_src = SRC / "bin" / platform_dir
suffix  = ".exe" if sys.platform == "win32" else ""

bundled_binaries = []
for name in ("ludusavi", "rclone"):
    exe = bin_src / f"{name}{suffix}"
    if exe.is_file():
        # destination path inside the frozen bundle: bin/<platform>/
        bundled_binaries.append((str(exe), f"bin/{platform_dir}"))

# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------
a = Analysis(
    [str(SRC / "app.py")],
    pathex=[str(ROOT / "src")],
    binaries=bundled_binaries,
    datas=[
        # ship the .env.example so first-run users have a template
        (str(ROOT / ".env.example"), "."),
    ],
    hiddenimports=[
        # PySide6 plugins that PyInstaller may miss
        "PySide6.QtSvg",
        "PySide6.QtXml",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # trim unused Qt modules to keep bundle size down
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtBluetooth",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtLocation",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSpatialAudio",
        "PySide6.QtTextToSpeech",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)  # noqa: F821

# --------------------------------------------------------------------------
# Single-file EXE  (--onefile equivalent)
# --------------------------------------------------------------------------
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="SaveSync-Bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",  # uncomment when you have an icon
)
