from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.core.compressor import Compressor
from app.models.job import Job, JobStatus
from app.utils.deps import check_ffmpeg_deps


pytestmark = pytest.mark.skipif(
    not check_ffmpeg_deps().ok,
    reason="ffmpeg/ffprobe tidak tersedia",
)


def _make_video(
    path: Path,
    *,
    duration: int = 3,
    with_audio: bool = True,
    rotate: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=1280x720:rate=30",
    ]
    if with_audio:
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={duration}",
                "-c:a",
                "aac",
                "-shortest",
            ]
        )
    else:
        cmd.append("-an")
    cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-b:v", "4M"])
    if rotate is not None:
        cmd.extend(["-metadata:s:v:0", f"rotate={rotate}"])
    cmd.append(str(path))
    subprocess.run(cmd, check=True)


def test_audio_less_encode(tmp_path: Path) -> None:
    src = tmp_path / "silent.mp4"
    out = tmp_path / "out.mp4"
    _make_video(src, with_audio=False, duration=3)

    job = Job(source_path=str(src), output_path=str(out))
    compressor = Compressor(
        target_size_mb=0.35,
        max_retries=3,
        preset="ultrafast",
        two_pass=False,
        hardware="cpu",
        crf_fallback=True,
    )
    result = compressor.compress_job(job)
    assert result.status == JobStatus.COMPLETED
    assert out.exists()
    assert out.stat().st_size <= 0.35 * 1024 * 1024


def test_two_pass_encode(tmp_path: Path) -> None:
    """Pass 1 menulis ke null device — harus jalan di semua platform."""
    src = tmp_path / "twopass.mp4"
    out = tmp_path / "out.mp4"
    _make_video(src, with_audio=True, duration=3)

    job = Job(source_path=str(src), output_path=str(out))
    compressor = Compressor(
        target_size_mb=0.4,
        max_retries=2,
        preset="ultrafast",
        two_pass=True,
        hardware="cpu",
        crf_fallback=True,
    )
    result = compressor.compress_job(job)
    assert result.status == JobStatus.COMPLETED, result.error
    assert out.exists()
    assert out.stat().st_size <= 0.4 * 1024 * 1024


def test_rotated_encode(tmp_path: Path) -> None:
    src = tmp_path / "rot.mp4"
    out = tmp_path / "out.mp4"
    _make_video(src, with_audio=True, duration=3, rotate=90)

    job = Job(source_path=str(src), output_path=str(out))
    compressor = Compressor(
        target_size_mb=0.4,
        max_retries=3,
        preset="ultrafast",
        two_pass=False,
        hardware="cpu",
        crf_fallback=True,
    )
    result = compressor.compress_job(job)
    assert result.status == JobStatus.COMPLETED
    assert "rot" in result.resolution or out.exists()
