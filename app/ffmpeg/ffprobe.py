from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.models.video import VideoInfo
from app.utils.paths import find_binary
from app.utils.proc import hidden_process_kwargs


class FFprobeError(RuntimeError):
    pass


def _ffprobe_bin() -> Path:
    path = find_binary("ffprobe")
    if path is None:
        raise FFprobeError(
            "FFprobe tidak ditemukan. Install FFmpeg atau letakkan binary di bin/."
        )
    return path


def probe_video(path: Path | str) -> VideoInfo:
    source = Path(path)
    if not source.exists():
        raise FFprobeError(f"File tidak ditemukan: {source}")

    cmd = [
        str(_ffprobe_bin()),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(source),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            errors="replace",
            **hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        raise FFprobeError(f"FFprobe timeout: {source}") from exc

    if result.returncode != 0:
        raise FFprobeError(
            f"FFprobe gagal untuk {source.name}: {result.stderr.strip() or 'unknown error'}"
        )

    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video_stream is None:
        raise FFprobeError(f"Tidak ada video stream: {source.name}")

    duration = float(fmt.get("duration") or video_stream.get("duration") or 0)
    file_size = int(fmt.get("size") or source.stat().st_size)

    fps = _parse_fps(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
    rotation = _parse_rotation(video_stream)

    return VideoInfo(
        path=str(source.resolve()),
        duration=duration,
        width=int(video_stream.get("width") or 0),
        height=int(video_stream.get("height") or 0),
        fps=fps,
        video_codec=str(video_stream.get("codec_name") or ""),
        audio_codec=str(audio_stream.get("codec_name") or "") if audio_stream else "",
        video_bitrate=int(video_stream.get("bit_rate") or 0),
        audio_bitrate=int(audio_stream.get("bit_rate") or 0) if audio_stream else 0,
        file_size=file_size,
        rotation=rotation,
    )


def _parse_fps(rate: str | None) -> float:
    if not rate or rate == "0/0":
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            den_f = float(den)
            if den_f == 0:
                return 0.0
            return float(num) / den_f
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def _parse_rotation(stream: dict) -> int:
    tags = stream.get("tags") or {}
    if "rotate" in tags:
        try:
            return int(float(tags["rotate"]))
        except ValueError:
            pass
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            try:
                return int(float(side["rotation"]))
            except ValueError:
                pass
    return 0
