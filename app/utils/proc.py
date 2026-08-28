from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

CREATE_NO_WINDOW = 0x08000000


def null_device() -> str:
    """Platform null sink: NUL on Windows, /dev/null elsewhere."""
    return os.devnull


def hidden_process_kwargs() -> dict[str, Any]:
    """
    Keyword args agar subprocess tidak memunculkan jendela console.

    Wajib di Windows untuk aplikasi GUI (PyInstaller --noconsole),
    karena tiap FFmpeg/FFprobe akan membuka terminal baru.
    """
    if not sys.platform.startswith("win"):
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE

    return {
        "startupinfo": startupinfo,
        "creationflags": CREATE_NO_WINDOW,
    }
