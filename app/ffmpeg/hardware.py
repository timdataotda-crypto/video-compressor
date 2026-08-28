from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import subprocess
import threading

from app.utils.logger import get_logger
from app.utils.paths import find_binary
from app.utils.proc import hidden_process_kwargs, null_device

logger = get_logger(__name__)


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


_probe_lock = threading.Lock()
_probe_cache: dict[str, bool] = {}


def reset_encoder_cache() -> None:
    with _probe_lock:
        _probe_cache.clear()


def mark_encoder_unusable(encoder: str) -> None:
    """Blacklist encoder setelah gagal saat runtime, agar job berikutnya tidak coba lagi."""
    with _probe_lock:
        _probe_cache[encoder] = False
    logger.warning("Encoder %s dinonaktifkan untuk sesi ini", encoder)


def _probe_encoder(encoder: str) -> bool:
    """
    Uji encoder dengan encode sintetis singkat.

    `ffmpeg -encoders` hanya melaporkan encoder yang dikompilasi, bukan yang
    didukung hardware. Build statis Windows selalu mencantumkan h264_nvenc dan
    h264_qsv walau GPU-nya tidak ada, jadi daftar itu tidak bisa dipercaya.
    """
    binary = _ffmpeg_bin()
    if not binary:
        return False
    cmd = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=320x240:r=10:d=0.5",
        "-c:v",
        encoder,
        "-frames:v",
        "5",
        "-f",
        "null",
        null_device(),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            errors="replace",
            **hidden_process_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        logger.info(
            "Probe encoder %s gagal: %s",
            encoder,
            (result.stderr or "").strip()[:200],
        )
        return False
    return True


def encoder_works(encoder: str) -> bool:
    if encoder == EncoderChoice.LIBX264.value:
        return True
    with _probe_lock:
        if encoder in _probe_cache:
            return _probe_cache[encoder]
    ok = _probe_encoder(encoder)
    with _probe_lock:
        _probe_cache[encoder] = ok
    return ok


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

    cpu = EncoderInfo(EncoderChoice.LIBX264, "CPU (libx264)")

    if preference == "cpu":
        return cpu

    if preference in mapping:
        chosen = mapping[preference]
        if chosen.name.value in available and encoder_works(chosen.name.value):
            return chosen
        return cpu

    # auto
    for key in ("h264_videotoolbox", "h264_nvenc", "h264_qsv"):
        if key not in available or not encoder_works(key):
            continue
        if key == "h264_videotoolbox":
            return EncoderInfo(EncoderChoice.VIDEOTOOLBOX, "Apple VideoToolbox")
        if key == "h264_nvenc":
            return EncoderInfo(EncoderChoice.NVENC, "NVIDIA NVENC")
        return EncoderInfo(EncoderChoice.QSV, "Intel QSV")

    return cpu
