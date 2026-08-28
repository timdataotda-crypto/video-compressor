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


def _make_sample(path: Path, duration: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
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
            "6M",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        capture_output=True,
        check=True,
    )


def _config(tmp_path: Path, workers: int) -> dict:
    return {
        "target_size_mb": 1.0,
        "safety_margin": 0.94,
        "retry_margin": 0.96,
        "max_retries": 3,
        "audio_bitrate_kbps": 64,
        "preset": "ultrafast",
        "resolution_mode": "auto",
        "workers": workers,
        "recursive": True,
        "preserve_structure": True,
        "skip_existing": False,
        "auto_retry": True,
        "hardware_acceleration": "cpu",
        "quality_profile": "fast",
        "crf_fallback": True,
    }


def test_batch_multiple_workers_all_succeed(tmp_path: Path) -> None:
    """
    Batch paralel harus menyelesaikan semua job tanpa bentrok
    lock SQLite maupun tabrakan file temporer.
    """
    source = tmp_path / "src"
    output = tmp_path / "out"
    for i in range(4):
        _make_sample(source / f"clip_{i}.mp4")

    db = Database(path=tmp_path / "jobs.db")
    manager = JobManager(config=_config(tmp_path, workers=3), db=db)

    jobs = manager.scan_and_create_jobs(source, output)
    assert len(jobs) == 4

    results = manager.run_batch(jobs, on_job_update=lambda j: None)

    failed = [(Path(j.source_path).name, j.error) for j in results if j.status != JobStatus.COMPLETED]
    assert not failed, f"job gagal: {failed}"
    assert len(results) == 4

    for job in results:
        out = Path(job.output_path)
        assert out.exists(), f"output hilang: {out}"
        assert out.stat().st_size <= 1.0 * 1024 * 1024

    # Status yang tersimpan di DB harus konsisten dengan hasil di memori.
    persisted = db.list_jobs()
    assert all(j.status == JobStatus.COMPLETED for j in persisted)
    assert all(j.progress >= 99.0 for j in persisted)


def test_batch_preserves_folder_structure(tmp_path: Path) -> None:
    source = tmp_path / "src"
    output = tmp_path / "out"
    _make_sample(source / "DAY_01" / "a.mp4")
    _make_sample(source / "DAY_02" / "b.mp4")

    db = Database(path=tmp_path / "jobs.db")
    manager = JobManager(config=_config(tmp_path, workers=2), db=db)
    jobs = manager.scan_and_create_jobs(source, output)
    results = manager.run_batch(jobs)

    assert all(j.status == JobStatus.COMPLETED for j in results)
    assert (output / "DAY_01" / "a.mp4").exists()
    assert (output / "DAY_02" / "b.mp4").exists()
