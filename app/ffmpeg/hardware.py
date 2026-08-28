from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import subprocess

from app.utils.paths import find_binary
from app.utils.proc import hidden_process_kwargs


class EncoderChoice(str, Enum):
    LIBX264 = "libx264"
    NVENC = "h264_nvenc"
    QSV = "h264_qsv"
    VIDEOTOOLBOX = "h264_videotoolbox"


@dataclass
class EncoderInfo:
    name: EncoderChoice
    label: str


def _ffmpeg_bin() -> str | None:
    path = find_binary("ffmpeg")
    return str(path) if path else None


def list_encoders() -> set[str]:
    binary = _ffmpeg_bin()
    if not binary:
        return set()
    try:
        result = subprocess.run(
            [binary, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            errors="replace",
            **hidden_process_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return set(result.stdout.split())


def detect_encoder(preference: str = "auto") -> EncoderInfo:
    preference = (preference or "auto").lower()
    available = list_encoders()

    mapping = {
        "cpu": EncoderInfo(EncoderChoice.LIBX264, "CPU (libx264)"),
        "nvidia": EncoderInfo(EncoderChoice.NVENC, "NVIDIA NVENC"),
        "nvenc": EncoderInfo(EncoderChoice.NVENC, "NVIDIA NVENC"),
        "intel": EncoderInfo(EncoderChoice.QSV, "Intel QSV"),
        "qsv": EncoderInfo(EncoderChoice.QSV, "Intel QSV"),
        "apple": EncoderInfo(EncoderChoice.VIDEOTOOLBOX, "Apple VideoToolbox"),
        "videotoolbox": EncoderInfo(EncoderChoice.VIDEOTOOLBOX, "Apple VideoToolbox"),
    }

    if preference in mapping and preference != "auto":
        chosen = mapping[preference]
        if chosen.name.value in available or preference == "cpu":
            return chosen
        return EncoderInfo(EncoderChoice.LIBX264, "CPU (libx264)")

    # auto
    for key in ("h264_videotoolbox", "h264_nvenc", "h264_qsv"):
        if key in available:
            if key == "h264_videotoolbox":
                return EncoderInfo(EncoderChoice.VIDEOTOOLBOX, "Apple VideoToolbox")
            if key == "h264_nvenc":
                return EncoderInfo(EncoderChoice.NVENC, "NVIDIA NVENC")
            return EncoderInfo(EncoderChoice.QSV, "Intel QSV")

    return EncoderInfo(EncoderChoice.LIBX264, "CPU (libx264)")
