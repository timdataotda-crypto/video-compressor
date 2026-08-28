from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_meipass() -> Path | None:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return None


def get_project_root() -> Path:
    """Source tree root (dev) or PyInstaller extract dir (frozen)."""
    meipass = get_meipass()
    if meipass is not None:
        return meipass
    return Path(__file__).resolve().parents[2]


def get_user_data_dir() -> Path:
    """Writable app data (config, logs, sqlite)."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "DroneCompressor"
    elif sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA")
        base = (
            Path(local) / "DroneCompressor"
            if local
            else Path.home() / "AppData" / "Local" / "DroneCompressor"
        )
    else:
        base = Path.home() / ".local" / "share" / "DroneCompressor"
    return ensure_dir(base)


def get_config_path() -> Path:
    if is_frozen():
        return get_user_data_dir() / "config.json"
    return get_project_root() / "config.json"


def get_logs_dir() -> Path:
    if is_frozen():
        return ensure_dir(get_user_data_dir() / "logs")
    return get_project_root() / "logs"


def get_temp_dir() -> Path:
    if is_frozen():
        return ensure_dir(get_user_data_dir() / ".temp")
    return get_project_root() / ".temp"


def get_output_dir() -> Path:
    return get_project_root() / "output"


def get_database_path() -> Path:
    if is_frozen():
        return get_user_data_dir() / "jobs.db"
    return ensure_dir(get_project_root() / "data") / "jobs.db"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


_DEFAULTS: dict[str, Any] = {
    "target_size_mb": 19,
    "safety_margin": 0.94,
    "retry_margin": 0.96,
    "max_retries": 4,
    "audio_bitrate_kbps": 96,
    "codec": "h264",
    "preset": "medium",
    "resolution_mode": "auto",
    "workers": 2,
    "recursive": True,
    "preserve_structure": True,
    "skip_existing": True,
    "auto_retry": True,
    "hardware_acceleration": "auto",
    "quality_profile": "balanced",
    "crf_fallback": True,
}


def _bundled_default_config() -> dict[str, Any]:
    candidates = [
        get_project_root() / "config.json",
    ]
    meipass = get_meipass()
    if meipass is not None:
        candidates.insert(0, meipass / "config.json")
    for path in candidates:
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                merged = dict(_DEFAULTS)
                merged.update(data)
                return merged
            except (OSError, json.JSONDecodeError):
                continue
    return dict(_DEFAULTS)


def load_config() -> dict[str, Any]:
    path = get_config_path()
    defaults = _bundled_default_config()
    if not path.exists():
        if is_frozen():
            save_config(defaults)
        return defaults
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    defaults.update(data)
    return defaults


def save_config(config: dict[str, Any]) -> None:
    path = get_config_path()
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def map_output_path(
    source_root: Path,
    source_file: Path,
    output_root: Path,
    preserve_structure: bool = True,
) -> Path:
    source_root = Path(source_root).resolve()
    source_file = Path(source_file).resolve()
    output_root = Path(output_root)
    if preserve_structure:
        try:
            relative = source_file.relative_to(source_root)
        except ValueError:
            relative = Path(source_file.name)
        return output_root / relative.with_suffix(".mp4")
    return output_root / f"{source_file.stem}.mp4"


def bundled_bin_dir() -> Path:
    root = get_project_root()
    if sys.platform == "darwin":
        return root / "bin" / "macos"
    if sys.platform.startswith("win"):
        return root / "bin" / "windows"
    return root / "bin" / "linux"


def find_binary(name: str) -> Path | None:
    """Locate ffmpeg/ffprobe: app bundle → PATH."""
    suffix = ".exe" if sys.platform.startswith("win") else ""
    filename = f"{name}{suffix}"
    candidates: list[Path] = []

    meipass = get_meipass()
    if meipass is not None:
        if sys.platform == "darwin":
            candidates.append(meipass / "bin" / "macos" / filename)
        elif sys.platform.startswith("win"):
            candidates.append(meipass / "bin" / "windows" / filename)
        else:
            candidates.append(meipass / "bin" / "linux" / filename)
        candidates.append(meipass / filename)
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / filename)
        # .app layout: Contents/MacOS/exe → Contents/Resources/bin/...
        candidates.append(exe_dir.parent / "Resources" / "bin" / "macos" / filename)
        candidates.append(exe_dir.parent / "Resources" / "bin" / "windows" / filename)
        candidates.append(exe_dir.parent / "Frameworks" / "bin" / "macos" / filename)

    candidates.append(bundled_bin_dir() / filename)

    for path in candidates:
        if path.exists() and path.is_file():
            # Skip broken symlinks pointing nowhere
            try:
                if path.resolve().exists():
                    return path.resolve()
            except OSError:
                continue

    found = shutil.which(name)
    if found:
        return Path(found)

    # macOS GUI apps often miss Homebrew in PATH
    if sys.platform == "darwin":
        for prefix in (
            Path("/usr/local/bin"),
            Path("/opt/homebrew/bin"),
            Path.home() / "bin",
        ):
            candidate = prefix / filename
            if candidate.exists():
                return candidate

    return None
