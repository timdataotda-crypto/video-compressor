# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Windows DroneCompressor.exe (one-folder)."""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
root = Path(SPECPATH).resolve()

datas = [
    (str(root / "config.json"), "."),
    (str(root / "app" / "ui" / "styles.qss"), "app/ui"),
]

bin_dir = root / "bin" / "windows"
for name in ("ffmpeg.exe", "ffprobe.exe"):
    binary = bin_dir / name
    if binary.exists():
        datas.append((str(binary), "bin/windows"))

pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")

a = Analysis(
    [str(root / "run_app.py")],
    pathex=[str(root)],
    binaries=pyside_binaries,
    datas=datas + pyside_datas,
    hiddenimports=list(pyside_hidden)
    + [
        "app",
        "app.main",
        "app.cli",
        "app.ui.main_window",
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
