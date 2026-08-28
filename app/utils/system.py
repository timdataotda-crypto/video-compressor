from __future__ import annotations

import shutil
from pathlib import Path


def get_free_disk_space_gb(path: Path) -> float:
    usage = shutil.disk_usage(path if path.exists() else path.parent)
    return usage.free / (1024**3)


def estimate_disk_space_needed(
    video_count: int,
    target_mb: float,
    buffer_factor: float = 1.5,
) -> float:
    """Rough estimate in GB for output + temp (two-pass / retry)."""
    bytes_needed = video_count * target_mb * 1024 * 1024 * buffer_factor
    return bytes_needed / (1024**3)
