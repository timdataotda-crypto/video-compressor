from __future__ import annotations

import os
import subprocess
import sys

from app.utils.proc import hidden_process_kwargs, null_device


def test_null_device_matches_platform() -> None:
    assert null_device() == os.devnull
    if sys.platform.startswith("win"):
        assert null_device().upper() == "NUL"
    else:
        assert null_device() == "/dev/null"


def test_hidden_kwargs_only_on_windows() -> None:
    kwargs = hidden_process_kwargs()
    if sys.platform.startswith("win"):
        assert "creationflags" in kwargs
        assert "startupinfo" in kwargs
    else:
        assert kwargs == {}


def test_hidden_kwargs_usable_in_subprocess() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "print('ok')"],
        capture_output=True,
        text=True,
        check=False,
        **hidden_process_kwargs(),
    )
    assert result.returncode == 0
    assert "ok" in result.stdout
