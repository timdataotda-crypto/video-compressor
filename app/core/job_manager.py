from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import re
import threading

from app.core.compressor import Compressor
from app.core.scanner import scan_videos
from app.core.bitrate import is_target_realistic, suggest_min_target_mb
from app.core.profiles import PROFILES, apply_quality_profile, normalize_profile_key
from app.database.database import Database
from app.ffmpeg.ffprobe import probe_video
from app.geopas.client import GeopasClient
from app.models.job import Job, JobStatus
from app.utils.logger import get_logger
from app.utils.paths import ensure_dir, load_config, map_output_path
from app.utils.system import estimate_disk_space_needed, get_free_disk_space_gb

logger = get_logger(__name__)

BatchCallback = Callable[[Job], None]
StatusCallback = Callable[[str], None]


def batch_folder_name(label: str, paket_id: Optional[int] = None) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", label or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")[:70]
    if not cleaned:
        cleaned = "batch"
    if paket_id is not None:
        suffix = f"_{paket_id}"
        if not cleaned.endswith(suffix):
            cleaned = f"{cleaned}{suffix}"
    return cleaned


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
        self._upload_lock = threading.Lock()
        self.geopas_client: Optional[GeopasClient] = None
        self.geopas_paket_id: Optional[int] = None

    def scan_and_create_jobs(
        self,
        source: Path,
        output: Path,
        clear_previous: bool = True,
        *,
        geopas_paket_id: Optional[int] = None,
        geopas_paket_nama: str = "",
        batch_source: str = "",
        batch_label: str = "",
        videos: Optional[list[Path]] = None,
    ) -> list[Job]:
        recursive = bool(self.config.get("recursive", True))
        preserve = bool(self.config.get("preserve_structure", True))
        skip_existing = bool(self.config.get("skip_existing", True))

        found = videos if videos is not None else scan_videos(source, recursive=recursive)
        if clear_previous:
            self.db.clear_jobs()

        out_root = Path(output)
        if batch_label:
            out_root = out_root / batch_folder_name(batch_label, geopas_paket_id)
        source_root = Path(source).resolve()
        locked_source = batch_source or str(source_root)

        jobs: list[Job] = []
        for video in found:
            out = map_output_path(source_root, video, out_root, preserve_structure=preserve)
            if skip_existing and out.exists():
                job = Job(
                    source_path=str(video),
                    output_path=str(out),
                    original_size=video.stat().st_size,
                    output_size=out.stat().st_size,
                    status=JobStatus.SKIPPED,
                    progress=100.0,
                    created_at=datetime.now().isoformat(timespec="seconds"),
                    geopas_paket_id=geopas_paket_id,
                    geopas_paket_nama=geopas_paket_nama,
                    batch_source=locked_source,
                )
            else:
                job = Job(
                    source_path=str(video),
                    output_path=str(out),
                    original_size=video.stat().st_size if video.exists() else 0,
                    status=JobStatus.PENDING,
                    created_at=datetime.now().isoformat(timespec="seconds"),
                    geopas_paket_id=geopas_paket_id,
                    geopas_paket_nama=geopas_paket_nama,
                    batch_source=locked_source,
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

            if job.status == JobStatus.SKIPPED:
                self.db.update_job(job)
                if on_job_update:
                    on_job_update(job)
                return job

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

            # FFmpeg memancarkan progress puluhan kali per detik. Menulis
            # semuanya ke SQLite membuat worker saling memperebutkan lock.
            last_written = {"pct": -1.0}

            def _progress(j: Job, pct: float, _msg: str) -> None:
                j.progress = pct
                if pct - last_written["pct"] >= 1.0 or pct >= 99.0:
                    last_written["pct"] = pct
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

    def jobs_ready_to_upload(self, jobs: Optional[list[Job]] = None) -> list[Job]:
        rows = jobs if jobs is not None else self.db.list_jobs()
        ready: list[Job] = []
        for job in rows:
            if job.status not in (
                JobStatus.COMPLETED,
                JobStatus.SKIPPED,
                JobStatus.UPLOAD_FAILED,
            ):
                continue
            if Path(job.output_path).is_file():
                ready.append(job)
        return ready

    def upload_jobs(
        self,
        jobs: list[Job],
        on_job_update: Optional[BatchCallback] = None,
        on_status: Optional[StatusCallback] = None,
    ) -> list[Job]:
        self._cancel_event.clear()
        self._pause_event.set()
        if not self.geopas_client:
            raise RuntimeError("Geopas belum dipilih.")
        has_paket = any(j.geopas_paket_id for j in jobs) or self.geopas_paket_id
        if not has_paket:
            raise RuntimeError("Tidak ada paket pekerjaan terkunci pada job.")
        results: list[Job] = []
        total = len(jobs)
        for index, job in enumerate(jobs, start=1):
            if self._cancel_event.is_set():
                break
            self._pause_event.wait()
            if on_status:
                dest = job.geopas_paket_nama or (
                    f"#{job.geopas_paket_id}" if job.geopas_paket_id else "Geopas"
                )
                on_status(
                    f"Mengunggah {index}/{total} ke {dest}: {Path(job.output_path).name}"
                )
            results.append(self._upload_one(job, on_job_update))
        if on_status:
            ok = sum(1 for j in results if j.status == JobStatus.COMPLETED and not j.error)
            failed = sum(1 for j in results if j.status == JobStatus.UPLOAD_FAILED)
            on_status(f"Unggah selesai. OK={ok} Gagal={failed}")
        return results

    def _upload_one(
        self,
        job: Job,
        on_job_update: Optional[BatchCallback],
    ) -> Job:
        output = Path(job.output_path)
        if not output.is_file():
            job.status = JobStatus.UPLOAD_FAILED
            job.error = "File output lokal tidak ditemukan."
            self.db.update_job(job)
            if on_job_update:
                on_job_update(job)
            return job
        job.status = JobStatus.UPLOADING
        job.error = ""
        self.db.update_job(job)
        if on_job_update:
            on_job_update(job)
        try:
            assert self.geopas_client is not None
            paket_id = job.geopas_paket_id or self.geopas_paket_id
            if not paket_id:
                raise RuntimeError("Job tidak punya paket pekerjaan terkunci.")
            self.geopas_client.upload_video(int(paket_id), output)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unggah Geopas gagal untuk %s", output.name)
            job.status = JobStatus.UPLOAD_FAILED
            job.progress = 100.0
            job.error = f"File lokal aman. Unggah Geopas gagal: {exc}"
            self.db.update_job(job)
            if on_job_update:
                on_job_update(job)
            return job
        job.status = JobStatus.COMPLETED
        job.progress = 100.0
        job.error = ""
        job.mark_completed()
        self.db.update_job(job)
        if on_job_update:
            on_job_update(job)
        return job

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
            "failed": sum(
                1
                for j in jobs
                if j.status in (JobStatus.FAILED, JobStatus.UPLOAD_FAILED)
            ),
            "pending": sum(1 for j in jobs if j.status == JobStatus.PENDING),
            "skipped": sum(1 for j in jobs if j.status == JobStatus.SKIPPED),
            "remaining": sum(
                1
                for j in jobs
                if j.status
                in (JobStatus.PENDING, JobStatus.FAILED, JobStatus.CANCELLED)
            ),
        }
