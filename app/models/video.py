from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VideoInfo:
    path: str
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    video_codec: str = ""
    audio_codec: str = ""
    video_bitrate: int = 0
    audio_bitrate: int = 0
    file_size: int = 0
    rotation: int = 0

    @property
    def file_size_mb(self) -> float:
        return self.file_size / (1024 * 1024)

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_codec)
