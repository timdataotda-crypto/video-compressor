from __future__ import annotations

from pathlib import Path

from app.core.bitrate import bytes_to_mb


def validate_size(path: Path | str, target_size_mb: float) -> tuple[bool, float]:
    """Return (ok, actual_size_mb)."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Output tidak ditemukan: {file_path}")
    actual_mb = bytes_to_mb(file_path.stat().st_size)
    return actual_mb <= target_size_mb, actual_mb
