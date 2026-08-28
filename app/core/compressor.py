from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

from app.core.analyzer import analyze_video
from app.core.bitrate import (
    bytes_to_mb,
    calculate_retry_bitrate_kbps,
    calculate_video_bitrate_kbps,
    clamp_bitrate_for_resolution,
    estimate_crf_ladder,
)
from app.core.filters import build_vf_filter
from app.core.validator import validate_size
from app.ffmpeg.ffmpeg import FFmpegError, FFmpegRunner
from app.models.job import Job, JobStatus
from app.utils.logger import get_logger
from app.utils.paths import ensure_dir, get_temp_dir

logger = get_logger("app.jobs")

ProgressCallback = Callable[[Job, float, str], None]


class Compressor:
    def __init__(
        self,
        target_size_mb: float = 19.0,
        safety_margin: float = 0.94,
        retry_margin: float = 0.96,
        max_retries: int = 4,
        audio_bitrate_kbps: int = 96,
        preset: str = "medium",
        resolution_mode: str = "auto",
        hardware: str = "auto",
        auto_retry: bool = True,
        two_pass: bool = False,
        crf_fallback: bool = True,
    ) -> None:
        self.target_size_mb = target_size_mb
        self.safety_margin = safety_margin
        self.retry_margin = retry_margin
        self.max_retries = max_retries
        self.audio_bitrate_kbps = audio_bitrate_kbps
        self.preset = preset
        self.resolution_mode = resolution_mode
        self.hardware = hardware
        self.auto_retry = auto_retry
        self.two_pass = two_pass
        self.crf_fallback = crf_fallback
        self._runner = FFmpegRunner(hardware=hardware)

    def cancel(self) -> None:
        self._runner.cancel()

    def compress_job(
        self,
        job: Job,
        on_progress: Optional[ProgressCallback] = None,
    ) -> Job:
        source = Path(job.source_path)
        output = Path(job.output_path)
        temp_dir = ensure_dir(
            get_temp_dir() / f"job_{abs(hash(job.source_path)) % 10_000_000}"
        )

        try:
            job.status = JobStatus.ANALYZING
            job.mark_started()
            if on_progress:
                on_progress(job, 0.0, "Menganalisis video…")

            info = analyze_video(source)
            job.duration = info.duration
            job.original_size = info.file_size
            include_audio = info.has_audio
            audio_kbps = self.audio_bitrate_kbps if include_audio else 0

            if info.duration <= 0:
                raise RuntimeError("Durasi video tidak valid")

            if info.file_size_mb <= self.target_size_mb:
                ensure_dir(output.parent)
                if source.resolve() != output.resolve():
                    shutil.copy2(source, output)
                job.output_size = output.stat().st_size
                job.resolution = f"{info.width}x{info.height}"
                job.mark_completed()
                logger.info("SKIP encode (already <= target): %s", source.name)
                return job

            bitrate = calculate_video_bitrate_kbps(
                duration_sec=info.duration,
                target_size_mb=self.target_size_mb,
                safety_margin=self.safety_margin,
                audio_bitrate_kbps=audio_kbps,
            )
            geometry = build_vf_filter(
                info.width,
                info.height,
                info.rotation,
                bitrate,
                mode=self.resolution_mode,
            )
            bitrate = clamp_bitrate_for_resolution(
                bitrate, geometry.display_width, geometry.display_height
            )
            job.video_bitrate = bitrate
            job.resolution = geometry.label

            attempts = self.max_retries if self.auto_retry else 1
            last_error = ""
            last_temp: Path | None = None

            for attempt in range(1, attempts + 1):
                job.attempt = attempt
                job.status = JobStatus.COMPRESSING
                temp_out = temp_dir / f"attempt_{attempt}.mp4"
                last_temp = temp_out

                geometry = build_vf_filter(
                    info.width,
                    info.height,
                    info.rotation,
                    bitrate,
                    mode=self.resolution_mode,
                )
                bitrate = clamp_bitrate_for_resolution(
                    bitrate, geometry.display_width, geometry.display_height
                )
                job.resolution = geometry.label
                job.video_bitrate = bitrate

                logger.info(
                    "JOB START %s attempt=%s bitrate=%sk resolution=%s audio=%s",
                    source.name,
                    attempt,
                    bitrate,
                    geometry.label,
                    include_audio,
                )

                def _progress(pct: float, msg: str, _job: Job = job) -> None:
                    _job.progress = pct
                    _job.status = JobStatus.COMPRESSING
                    if on_progress:
                        on_progress(_job, pct, msg)

                try:
                    self._runner.encode(
                        input_path=source,
                        output_path=temp_out,
                        video_bitrate_kbps=bitrate,
                        audio_bitrate_kbps=audio_kbps,
                        include_audio=include_audio,
                        scale_filter=geometry.vf_filter,
                        duration=info.duration,
                        preset=self.preset,
                        two_pass=self.two_pass,
                        passlog_prefix=temp_dir / f"pass_{attempt}",
                        on_progress=_progress,
                        mode="abr",
                    )
                except FFmpegError as exc:
                    last_error = str(exc)
                    if "dibatalkan" in last_error.lower():
                        job.status = JobStatus.CANCELLED
                        job.error = last_error
                        return job
                    logger.warning("ABR encode error: %s", last_error)
                    continue

                job.status = JobStatus.VALIDATING
                ok, actual_mb = validate_size(temp_out, self.target_size_mb)
                job.output_size = temp_out.stat().st_size
                job.progress = 99.0

                if ok:
                    return self._finalize_success(
                        job, temp_out, output, bitrate, temp_dir
                    )

                bitrate = calculate_retry_bitrate_kbps(
                    current_bitrate_kbps=bitrate,
                    target_size_mb=self.target_size_mb,
                    actual_size_mb=actual_mb,
                    retry_margin=self.retry_margin,
                )
                last_error = (
                    f"Hasil {actual_mb:.2f} MB masih > {self.target_size_mb} MB"
                )
                logger.warning(
                    "RETRY %s actual=%.2fMB new_bitrate=%sk",
                    source.name,
                    actual_mb,
                    bitrate,
                )

            # CRF hybrid fallback after ABR exhausted
            if self.crf_fallback and self.auto_retry:
                result = self._crf_fallback(
                    job=job,
                    source=source,
                    output=output,
                    temp_dir=temp_dir,
                    info_rotation=info.rotation,
                    info_width=info.width,
                    info_height=info.height,
                    duration=info.duration,
                    include_audio=include_audio,
                    audio_kbps=audio_kbps,
                    bitrate_hint=bitrate,
                    on_progress=on_progress,
                )
                if result is not None:
                    return result

            job.status = JobStatus.FAILED
            job.error = last_error or "Gagal mencapai target ukuran"
            if last_temp and last_temp.exists():
                job.output_size = last_temp.stat().st_size
            logger.error("FAILED %s: %s", source.name, job.error)
            return job

        except Exception as exc:  # noqa: BLE001
            job.status = JobStatus.FAILED
            job.error = str(exc)
            logger.exception("FAILED %s", source.name)
            return job
        finally:
            self._cleanup_temp(temp_dir)

    def _crf_fallback(
        self,
        job: Job,
        source: Path,
        output: Path,
        temp_dir: Path,
        info_rotation: int,
        info_width: int,
        info_height: int,
        duration: float,
        include_audio: bool,
        audio_kbps: int,
        bitrate_hint: int,
        on_progress: Optional[ProgressCallback],
    ) -> Job | None:
        geometry = build_vf_filter(
            info_width,
            info_height,
            info_rotation,
            max(bitrate_hint, 200),
            mode=self.resolution_mode,
        )
        job.resolution = f"{geometry.label} CRF"

        for crf in estimate_crf_ladder(start=26):
            job.attempt += 1
            job.status = JobStatus.COMPRESSING
            temp_out = temp_dir / f"crf_{crf}.mp4"
            logger.info(
                "CRF FALLBACK %s crf=%s resolution=%s",
                source.name,
                crf,
                geometry.label,
            )

            def _progress(pct: float, msg: str, _job: Job = job) -> None:
                _job.progress = pct
                if on_progress:
                    on_progress(_job, pct, msg)

            try:
                self._runner.encode(
                    input_path=source,
                    output_path=temp_out,
                    video_bitrate_kbps=bitrate_hint,
                    audio_bitrate_kbps=audio_kbps,
                    include_audio=include_audio,
                    scale_filter=geometry.vf_filter,
                    duration=duration,
                    preset=self.preset,
                    two_pass=False,
                    on_progress=_progress,
                    mode="crf",
                    crf=crf,
                )
            except FFmpegError as exc:
                if "dibatalkan" in str(exc).lower():
                    job.status = JobStatus.CANCELLED
                    job.error = str(exc)
                    return job
                logger.warning("CRF encode error crf=%s: %s", crf, exc)
                continue

            ok, actual_mb = validate_size(temp_out, self.target_size_mb)
            job.output_size = temp_out.stat().st_size
            if ok:
                logger.info(
                    "COMPLETED via CRF %s crf=%s output=%.2fMB",
                    source.name,
                    crf,
                    actual_mb,
                )
                return self._finalize_success(
                    job, temp_out, output, bitrate_hint, temp_dir
                )
            logger.warning(
                "CRF %s still large: %.2fMB > %.2fMB",
                crf,
                actual_mb,
                self.target_size_mb,
            )
        return None

    def _finalize_success(
        self,
        job: Job,
        temp_out: Path,
        output: Path,
        bitrate: int,
        temp_dir: Path,
    ) -> Job:
        ensure_dir(output.parent)
        if output.exists():
            output.unlink()
        try:
            temp_out.replace(output)
        except OSError:
            # Beda drive/volume (umum di Windows: temp di C:, output di D:)
            shutil.move(str(temp_out), str(output))
        job.output_size = output.stat().st_size
        job.video_bitrate = bitrate
        job.mark_completed()
        logger.info(
            "COMPLETED %s output=%.2fMB bitrate=%sk",
            Path(job.source_path).name,
            bytes_to_mb(job.output_size),
            bitrate,
        )
        self._cleanup_temp(temp_dir)
        return job

    @staticmethod
    def _cleanup_temp(temp_dir: Path) -> None:
        if not temp_dir.exists():
            return
        for child in temp_dir.iterdir():
            try:
                if child.is_file():
                    child.unlink()
            except OSError:
                pass
        try:
            temp_dir.rmdir()
        except OSError:
            pass
