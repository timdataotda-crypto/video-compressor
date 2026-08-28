from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.utils.paths import find_binary
from app.utils.proc import hidden_process_kwargs


INSTALL_HINT = """FFmpeg/FFprobe wajib ada agar aplikasi bisa bekerja.

macOS:
  brew install ffmpeg

Windows:
  Install FFmpeg lalu pastikan ada di PATH,
  atau letakkan ffmpeg.exe & ffprobe.exe di folder bin/windows/

Atau salin binary ke:
  bin/macos/   (macOS)
  bin/windows/ (Windows)
"""


@dataclass
class DependencyStatus:
    ffmpeg: Path | None
    ffprobe: Path | None
    ffmpeg_version: str = ""
    ok: bool = False
    message: str = ""


def probe_version(binary: Path) -> str:
    try:
        result = subprocess.run(
            [str(binary), "-version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            errors="replace",
            **hidden_process_kwargs(),
        )
        first = (result.stdout or result.stderr or "").splitlines()
        return first[0].strip() if first else str(binary)
    except (OSError, subprocess.TimeoutExpired):
        return str(binary)


def check_ffmpeg_deps() -> DependencyStatus:
    ffmpeg = find_binary("ffmpeg")
    ffprobe = find_binary("ffprobe")
    status = DependencyStatus(ffmpeg=ffmpeg, ffprobe=ffprobe)

    missing: list[str] = []
    if ffmpeg is None:
        missing.append("ffmpeg")
    if ffprobe is None:
        missing.append("ffprobe")

    if missing:
        status.ok = False
        status.message = (
            f"Tidak ditemukan: {', '.join(missing)}.\n\n{INSTALL_HINT}"
        )
        return status

    assert ffmpeg is not None and ffprobe is not None
    status.ffmpeg_version = probe_version(ffmpeg)
    # smoke: ffprobe must also run
    _ = probe_version(ffprobe)
    status.ok = True
    status.message = (
        f"FFmpeg OK\n{status.ffmpeg_version}\n"
        f"ffmpeg: {ffmpeg}\nffprobe: {ffprobe}"
    )
    return status


def require_ffmpeg_deps() -> DependencyStatus:
    status = check_ffmpeg_deps()
    if not status.ok:
        raise RuntimeError(status.message)
    return status
