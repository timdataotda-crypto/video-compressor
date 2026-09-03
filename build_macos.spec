# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — macOS DroneCompressor.app"""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None
root = Path(SPECPATH).resolve()

datas = [
    (str(root / "config.json"), "."),
    (str(root / "logo-geopas.png"), "."),
    (str(root / "app" / "ui" / "styles.qss"), "app/ui"),
]

bin_dir = root / "bin" / "macos"
for name in ("ffmpeg", "ffprobe"):
    binary = bin_dir / name
    if binary.exists() and not binary.is_symlink():
        datas.append((str(binary), "bin/macos"))
    elif binary.exists() and binary.is_symlink():
        # Resolve symlink to real file if possible (may still need dylibs)
        try:
            real = binary.resolve()
            if real.exists() and real.is_file():
                datas.append((str(real), "bin/macos"))
        except OSError:
            pass

pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")
certifi_datas = collect_data_files("certifi")

a = Analysis(
    [str(root / "run_app.py")],
    pathex=[str(root)],
    binaries=pyside_binaries,
    datas=datas + pyside_datas + certifi_datas,
    hiddenimports=list(pyside_hidden) + [
        "app",
        "app.main",
        "app.cli",
        "app.ui.main_window",
        "app.core.compressor",
        "app.geopas.client",
        "app.ffmpeg.ffmpeg",
        "app.ffmpeg.ffprobe",
        "certifi",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DroneCompressor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DroneCompressor",
)

app = BUNDLE(
    coll,
    name="DroneCompressor.app",
    icon=None,
    bundle_identifier="com.dronecompressor.app",
    info_plist={
        "CFBundleName": "Drone Compressor",
        "CFBundleDisplayName": "Drone Compressor",
        "CFBundleShortVersionString": "0.2.2",
        "CFBundleVersion": "0.2.2",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "NSQuitAlwaysKeepsWindows": False,
        "LSMultipleInstancesProhibited": True,
    },
)
