from __future__ import annotations

from pathlib import Path

from app.ffmpeg.ffprobe import probe_video
from app.models.video import VideoInfo


def analyze_video(path: Path | str) -> VideoInfo:
    return probe_video(path)
