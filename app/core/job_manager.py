from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import threading

from app.core.compressor import Compressor
from app.core.scanner import scan_videos
from app.core.bitrate import is_target_realistic, suggest_min_target_mb
from app.core.profiles import PROFILES, apply_quality_profile, normalize_profile_key
from app.database.database import Database
from app.ffmpeg.ffprobe import probe_video
from app.models.job import Job, JobStatus
from app.utils.logger import get_logger
from app.utils.paths import ensure_dir, load_config, map_output_path
from app.utils.system import estimate_disk_space_needed, get_free_disk_space_gb

logger = get_logger(__name__)

BatchCallback = Callable[[Job], None]
StatusCallback = Callable[[str], None]


class JobManager:
    def __init__(
        self,
        config: Optional[dict] = None,
        db: Optional[Database] = None,
    ) -> None:
        self.config = config or load_config()
        self.db = db or Database()
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # not paused
        self._active_compressors: list[Compressor] = []
        self._lock = threading.Lock()

    def scan_and_create_jobs(
        self,
        source: Path,
        output: Path,
        clear_previous: bool = True,
    ) -> list[Job]:
        recursive = bool(self.config.get("recursive", True))
        preserve = bool(self.config.get("preserve_structure", True))
        skip_existing = bool(self.config.get("skip_existing", True))

        videos = scan_videos(source, recursive=recursive)
        if clear_previous:
            self.db.clear_jobs()

        jobs: list[Job] = []
        for video in videos:
            out = map_output_path(source, video, output, preserve_structure=preserve)
            if skip_existing and out.exists():
                job = Job(
                    source_path=str(video),
                    output_path=str(out),
                    original_size=video.stat().st_size,
                    output_size=out.stat().st_size,
                    status=JobStatus.SKIPPED,
                    progress=100.0,
                    created_at=datetime.now().isoformat(timespec="seconds"),
                )
            else:
                job = Job(
                    source_path=str(video),
                    output_path=str(out),
                    original_size=video.stat().st_size if video.exists() else 0,
                    status=JobStatus.PENDING,
                    created_at=datetime.now().isoformat(timespec="seconds"),
                )
            job_id = self.db.insert_job(job)
            job.id = job_id
            jobs.append(job)
        return jobs

    def check_disk_space(self, output: Path, job_count: int) -> tuple[bool, float, float]:
        needed = estimate_disk_space_needed(
            job_count, float(self.config.get("target_size_mb", 19))
        )
        free = get_free_disk_space_gb(ensure_dir(output))
        return free >= needed, free, needed

    def collect_target_warnings(self, jobs: list[Job]) -> list[str]:
        """Warn when target size is likely too small for video duration."""
        target = float(self.config.get("target_size_mb", 19))
        safety = float(self.config.get("safety_margin", 0.94))
        audio = int(self.config.get("audio_bitrate_kbps", 96))
        warnings: list[str] = []

        for job in jobs:
            if job.status == JobStatus.SKIPPED:
                continue
            duration = job.duration
            if duration <= 0:
                try:
                    info = probe_video(job.source_path)
                    duration = info.duration
                    job.duration = duration
                    self.db.update_job(job)
                except Exception:  # noqa: BLE001
                    continue
            ok, _bitrate, msg = is_target_realistic(
                duration_sec=duration,
                target_size_mb=target,
                safety_margin=safety,
                audio_bitrate_kbps=audio,
            )
            if not ok:
                name = Path(job.source_path).name
                suggested = suggest_min_target_mb(duration, safety, audio)
                warnings.append(f"{name}: {msg} Saran target ≥ {suggested} MB.")
        return warnings

    def run_batch(
        self,
        jobs: Optional[list[Job]] = None,
        on_job_update: Optional[BatchCallback] = None,
        on_status: Optional[StatusCallback] = None,
        only_pending: bool = True,
    ) -> list[Job]:
        self._cancel_event.clear()
        self._pause_event.set()

        if jobs is None:
            statuses = [JobStatus.PENDING, JobStatus.FAILED, JobStatus.CANCELLED]
            if only_pending:
                jobs = self.db.list_jobs(statuses=statuses)
            else:
                jobs = self.db.list_jobs()

        work = [
            j
            for j in jobs
            if j.status
            in (JobStatus.PENDING, JobStatus.FAILED, JobStatus.CANCELLED)
        ]

        workers = max(1, int(self.config.get("workers", 2)))
        if on_status:
            on_status(f"Memproses {len(work)} video dengan {workers} worker…")

        self.config = apply_quality_profile(self.config)
        profile = PROFILES[normalize_profile_key(self.config.get("quality_profile"))]
        two_pass = profile.two_pass

        def process_one(job: Job) -> Job:
            if self._cancel_event.is_set():
                job.status = JobStatus.CANCELLED
                self.db.update_job(job)
                return job

            self._pause_event.wait()

            compressor = Compressor(
                target_size_mb=float(self.config.get("target_size_mb", 19)),
                safety_margin=float(self.config.get("safety_margin", 0.94)),
                retry_margin=float(self.config.get("retry_margin", 0.96)),
                max_retries=int(self.config.get("max_retries", 4)),
                audio_bitrate_kbps=int(self.config.get("audio_bitrate_kbps", 96)),
                preset=str(self.config.get("preset", profile.ffmpeg_preset)),
                resolution_mode=str(
                    self.config.get("resolution_mode", profile.resolution_mode)
                ),
                hardware=str(self.config.get("hardware_acceleration", "auto")),
                auto_retry=bool(self.config.get("auto_retry", True)),
                two_pass=two_pass,
                crf_fallback=bool(self.config.get("crf_fallback", True)),
            )
            with self._lock:
                self._active_compressors.append(compressor)

            def _progress(j: Job, pct: float, _msg: str) -> None:
                j.progress = pct
                self.db.update_job(j)
                if on_job_update:
                    on_job_update(j)

            try:
                result = compressor.compress_job(job, on_progress=_progress)
            finally:
                with self._lock:
                    if compressor in self._active_compressors:
                        self._active_compressors.remove(compressor)
            self.db.update_job(result)
            if on_job_update:
                on_job_update(result)
            return result

        results: list[Job] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process_one, job): job for job in work}
            for future in as_completed(futures):
                if self._cancel_event.is_set():
                    break
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    job = futures[future]
                    job.status = JobStatus.FAILED
                    job.error = str(exc)
                    self.db.update_job(job)
                    results.append(job)
                    if on_job_update:
                        on_job_update(job)

        if on_status:
            done = sum(1 for j in results if j.status == JobStatus.COMPLETED)
            failed = sum(1 for j in results if j.status == JobStatus.FAILED)
            on_status(f"Selesai. Completed={done} Failed={failed}")
        return results

    def cancel(self) -> None:
        self._cancel_event.set()
        with self._lock:
            for compressor in list(self._active_compressors):
                compressor.cancel()

    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()

    def get_summary(self) -> dict[str, int]:
        jobs = self.db.list_jobs()
        return {
            "total": len(jobs),
            "done": sum(1 for j in jobs if j.status == JobStatus.COMPLETED),
            "failed": sum(1 for j in jobs if j.status == JobStatus.FAILED),
            "pending": sum(1 for j in jobs if j.status == JobStatus.PENDING),
            "skipped": sum(1 for j in jobs if j.status == JobStatus.SKIPPED),
            "remaining": sum(
                1
                for j in jobs
                if j.status
                in (JobStatus.PENDING, JobStatus.FAILED, JobStatus.CANCELLED)
            ),
        }
