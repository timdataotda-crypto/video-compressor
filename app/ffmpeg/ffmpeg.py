from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

from app.ffmpeg.hardware import EncoderChoice, detect_encoder
from app.utils.paths import find_binary
from app.utils.proc import hidden_process_kwargs, null_device


class FFmpegError(RuntimeError):
    pass


ProgressCallback = Callable[[float, str], None]


class FFmpegRunner:
    def __init__(self, hardware: str = "auto") -> None:
        self.hardware = hardware
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def encode(
        self,
        input_path: Path,
        output_path: Path,
        video_bitrate_kbps: int = 0,
        audio_bitrate_kbps: int = 96,
        include_audio: bool = True,
        scale_filter: Optional[str] = None,
        duration: float = 0.0,
        preset: str = "medium",
        two_pass: bool = False,
        passlog_prefix: Optional[Path] = None,
        on_progress: Optional[ProgressCallback] = None,
        mode: str = "abr",
        crf: int = 28,
    ) -> None:
        """
        mode:
          - abr: target bitrate (-b:v)
          - crf: constant rate factor (libx264 only; others fall back to abr)
        """
        self._cancelled = False
        encoder = detect_encoder(self.hardware)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        use_crf = mode == "crf" and encoder.name == EncoderChoice.LIBX264
        use_two_pass = (
            two_pass
            and encoder.name == EncoderChoice.LIBX264
            and not use_crf
        )

        if use_two_pass:
            prefix = passlog_prefix or (output_path.parent / f".pass_{output_path.stem}")
            self._run_pass(
                input_path=input_path,
                output_path=Path(null_device()),
                video_bitrate_kbps=video_bitrate_kbps,
                audio_bitrate_kbps=audio_bitrate_kbps,
                include_audio=False,
                scale_filter=scale_filter,
                duration=duration,
                preset=preset,
                encoder=encoder.name,
                pass_num=1,
                passlog=prefix,
                on_progress=on_progress,
                progress_offset=0.0,
                progress_scale=0.45,
                mode="abr",
                crf=crf,
            )
            self._run_pass(
                input_path=input_path,
                output_path=output_path,
                video_bitrate_kbps=video_bitrate_kbps,
                audio_bitrate_kbps=audio_bitrate_kbps,
                include_audio=include_audio,
                scale_filter=scale_filter,
                duration=duration,
                preset=preset,
                encoder=encoder.name,
                pass_num=2,
                passlog=prefix,
                on_progress=on_progress,
                progress_offset=0.45,
                progress_scale=0.55,
                mode="abr",
                crf=crf,
            )
            self._cleanup_passlog(prefix)
            return

        self._run_pass(
            input_path=input_path,
            output_path=output_path,
            video_bitrate_kbps=video_bitrate_kbps,
            audio_bitrate_kbps=audio_bitrate_kbps,
            include_audio=include_audio,
            scale_filter=scale_filter,
            duration=duration,
            preset=preset,
            encoder=encoder.name,
            pass_num=0,
            passlog=None,
            on_progress=on_progress,
            progress_offset=0.0,
            progress_scale=1.0,
            mode="crf" if use_crf else "abr",
            crf=crf,
        )

    def _run_pass(
        self,
        input_path: Path,
        output_path: Path,
        video_bitrate_kbps: int,
        audio_bitrate_kbps: int,
        include_audio: bool,
        scale_filter: Optional[str],
        duration: float,
        preset: str,
        encoder: EncoderChoice,
        pass_num: int,
        passlog: Optional[Path],
        on_progress: Optional[ProgressCallback],
        progress_offset: float,
        progress_scale: float,
        mode: str,
        crf: int,
    ) -> None:
        binary = find_binary("ffmpeg")
        if binary is None:
            raise FFmpegError(
                "FFmpeg tidak ditemukan. Install FFmpeg atau letakkan binary di bin/."
            )

        cmd = [
            str(binary),
            "-y",
            "-hide_banner",
            "-i",
            str(input_path),
        ]

        if scale_filter:
            cmd.extend(["-vf", scale_filter])

        cmd.extend(["-c:v", encoder.value])

        if encoder == EncoderChoice.LIBX264:
            cmd.extend(["-preset", preset])
            if mode == "crf":
                cmd.extend(["-crf", str(crf)])
            else:
                cmd.extend(["-b:v", f"{max(video_bitrate_kbps, 50)}k"])
            if pass_num in (1, 2) and passlog is not None:
                cmd.extend(["-pass", str(pass_num), "-passlogfile", str(passlog)])
        else:
            # HW encoders: bitrate mode only
            cmd.extend(["-b:v", f"{max(video_bitrate_kbps, 50)}k"])

        if pass_num == 1:
            cmd.extend(["-an", "-f", "null", str(output_path)])
        else:
            self._append_audio_args(cmd, include_audio, audio_bitrate_kbps)
            if scale_filter and "transpose=" in scale_filter:
                cmd.extend(["-metadata:s:v:0", "rotate=0"])
            cmd.extend(["-movflags", "+faststart", str(output_path)])

        self._execute(cmd, duration, on_progress, progress_offset, progress_scale)

    @staticmethod
    def _append_audio_args(
        cmd: list[str],
        include_audio: bool,
        audio_bitrate_kbps: int,
    ) -> None:
        if not include_audio or audio_bitrate_kbps <= 0:
            cmd.append("-an")
            return
        cmd.extend(["-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"])

    def _execute(
        self,
        cmd: list[str],
        duration: float,
        on_progress: Optional[ProgressCallback],
        progress_offset: float,
        progress_scale: float,
    ) -> None:
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            universal_newlines=True,
            errors="replace",
            **hidden_process_kwargs(),
        )
        assert self._proc.stderr is not None

        time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
        stderr_lines: list[str] = []

        for line in self._proc.stderr:
            stderr_lines.append(line)
            if self._cancelled:
                break
            match = time_re.search(line)
            if match and duration > 0 and on_progress:
                h, m, s = match.groups()
                current = int(h) * 3600 + int(m) * 60 + float(s)
                ratio = min(1.0, current / duration)
                pct = (progress_offset + ratio * progress_scale) * 100
                on_progress(pct, line.strip())

        code = self._proc.wait()
        self._proc = None

        if self._cancelled:
            raise FFmpegError("Encoding dibatalkan")
        if code != 0:
            tail = "".join(stderr_lines[-20:]).strip()
            raise FFmpegError(f"FFmpeg gagal (exit {code}): {tail}")

    @staticmethod
    def _cleanup_passlog(prefix: Path) -> None:
        for suffix in ("-0.log", "-0.log.mbtree", ".log", ".log.mbtree"):
            path = Path(str(prefix) + suffix)
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
