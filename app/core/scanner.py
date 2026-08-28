from __future__ import annotations

from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".avi"}
TEMP_PREFIXES = (".", "~", "._")
TEMP_SUFFIXES = (".tmp", ".part", ".download")


def scan_videos(
    source: Path | str,
    recursive: bool = True,
) -> list[Path]:
    root = Path(source)
    if not root.exists():
        raise FileNotFoundError(f"Source folder tidak ditemukan: {root}")
    if root.is_file():
        if _is_video(root):
            return [root.resolve()]
        raise ValueError(f"Bukan file video: {root}")

    pattern = "**/*" if recursive else "*"
    results: list[Path] = []
    for path in sorted(root.glob(pattern)):
        if path.is_file() and _is_video(path) and not _is_temp(path):
            results.append(path.resolve())
    return results


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def _is_temp(path: Path) -> bool:
    name = path.name
    if name.startswith(TEMP_PREFIXES):
        return True
    lower = name.lower()
    return any(lower.endswith(s) for s in TEMP_SUFFIXES)
