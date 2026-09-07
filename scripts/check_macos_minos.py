#!/usr/bin/env python3
"""Fail the macOS build if bundled Mach-O files require newer than Monterey 12."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

MAX_MINOS = (12, 0)


def _parse_version(raw: str) -> tuple[int, int]:
    parts = raw.strip().split(".")
    major = int(parts[0]) if parts and parts[0].isdigit() else 0
    minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return major, minor


def macho_minos(path: Path) -> tuple[int, int] | None:
    try:
        out = subprocess.check_output(
            ["otool", "-l", str(path)],
            stderr=subprocess.DEVNULL,
            text=True,
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    if "Mach header" not in out and "fat_magic" not in out:
        return None
    highest: tuple[int, int] | None = None
    lines = out.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("minos"):
            ver = _parse_version(stripped.split()[-1])
        elif stripped.startswith("version") and i > 0 and "VERSION_MIN_MACOSX" in lines[i - 1]:
            ver = _parse_version(stripped.split()[-1])
        else:
            continue
        if highest is None or ver > highest:
            highest = ver
    return highest


def iter_candidates(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix in {".py", ".pyc", ".pyi", ".qml", ".qm", ".png", ".svg", ".txt", ".json", ".qss"}:
            continue
        files.append(path)
    return files


def check_tree(root: Path) -> list[str]:
    too_new: list[str] = []
    for path in iter_candidates(root):
        minos = macho_minos(path)
        if minos is None:
            continue
        if minos > MAX_MINOS:
            too_new.append(f"{minos[0]}.{minos[1]}  {path}")
    return too_new


def pyside_roots() -> list[Path]:
    try:
        import PySide6
    except ImportError:
        return []
    return [Path(PySide6.__file__).resolve().parent]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--pyside", action="store_true", help="Check installed PySide6/Qt libs")
    args = parser.parse_args()

    if shutil.which("otool") is None:
        print("otool tidak ada — skip cek minos")
        return 0

    roots = list(args.paths)
    if args.pyside:
        roots.extend(pyside_roots())
    if not roots:
        parser.error("beri path .app / binary, atau --pyside")

    too_new: list[str] = []
    for root in roots:
        if not root.exists():
            print(f"tidak ditemukan: {root}", file=sys.stderr)
            return 1
        too_new.extend(check_tree(root))

    if too_new:
        print(
            "Binary ini butuh macOS lebih baru dari Monterey 12, "
            "jadi akan gagal start di 12.7.6:",
            file=sys.stderr,
        )
        for line in too_new[:40]:
            print(f"  {line}", file=sys.stderr)
        if len(too_new) > 40:
            print(f"  … {len(too_new) - 40} lagi", file=sys.stderr)
        print("Pin PySide6 ke 6.9.x (wheel macosx_12_0).", file=sys.stderr)
        return 1

    print(f"OK: tidak ada Mach-O dengan minos > {MAX_MINOS[0]}.{MAX_MINOS[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
