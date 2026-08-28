from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.core.job_manager import JobManager
from app.database.database import Database
from app.models.job import JobStatus
from app.utils.deps import check_ffmpeg_deps


pytestmark = pytest.mark.skipif(
    not check_ffmpeg_deps().ok,
    reason="ffmpeg/ffprobe tidak tersedia",
)


def _make_sample(path: Path, duration: int = 4, bitrate: str = "8M") -> None:
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
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=1000:duration={duration}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-b:v",
        bitrate,
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    subprocess.run(cmd, check=True)


def test_end_to_end_compress(tmp_path: Path) -> None:
    source = tmp_path / "DRONE"
    output = tmp_path / "OUT"
    sample = source / "DAY_01" / "DJI_001.mp4"
    _make_sample(sample, duration=5, bitrate="6M")

    db = Database(path=tmp_path / "jobs.db")
    manager = JobManager(
        config={
            "target_size_mb": 0.4,
            "safety_margin": 0.94,
            "retry_margin": 0.96,
            "max_retries": 4,
            "audio_bitrate_kbps": 96,
            "preset": "ultrafast",
            "resolution_mode": "auto",
            "workers": 1,
            "recursive": True,
            "preserve_structure": True,
            "skip_existing": False,
            "auto_retry": True,
            "hardware_acceleration": "cpu",
            "quality_profile": "fast",
        },
        db=db,
    )
    jobs = manager.scan_and_create_jobs(source, output)
    assert len(jobs) == 1
    results = manager.run_batch(jobs=jobs)
    assert results[0].status == JobStatus.COMPLETED

    out_file = output / "DAY_01" / "DJI_001.mp4"
    assert out_file.exists()
    assert out_file.stat().st_size <= 0.4 * 1024 * 1024
    # original untouched
    assert sample.exists()
    assert sample.stat().st_size > out_file.stat().st_size


def test_deps_report_ok() -> None:
    status = check_ffmpeg_deps()
    assert status.ok
    assert status.ffmpeg is not None
    assert status.ffprobe is not None
    assert "ffmpeg" in status.ffmpeg_version.lower() or status.ffmpeg_version
