from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.ffmpeg import hardware
from app.ffmpeg.hardware import EncoderChoice, detect_encoder, reset_encoder_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_encoder_cache()
    yield
    reset_encoder_cache()


def test_listed_but_broken_encoder_falls_back_to_cpu(monkeypatch) -> None:
    """
    Kasus Windows: build statis mencantumkan h264_nvenc walau GPU tidak ada.

    Daftar `-encoders` saja tidak boleh dipercaya; probe harus menolaknya.
    """
    monkeypatch.setattr(hardware, "list_encoders", lambda: {"h264_nvenc", "libx264"})
    monkeypatch.setattr(hardware, "_probe_encoder", lambda enc: False)

    assert detect_encoder("auto").name == EncoderChoice.LIBX264
    assert detect_encoder("nvidia").name == EncoderChoice.LIBX264


def test_working_encoder_is_used(monkeypatch) -> None:
    monkeypatch.setattr(hardware, "list_encoders", lambda: {"h264_nvenc", "libx264"})
    monkeypatch.setattr(hardware, "_probe_encoder", lambda enc: True)

    assert detect_encoder("auto").name == EncoderChoice.NVENC


def test_probe_result_is_cached(monkeypatch) -> None:
    calls: list[str] = []

    def fake_probe(enc: str) -> bool:
        calls.append(enc)
        return False

    monkeypatch.setattr(hardware, "list_encoders", lambda: {"h264_nvenc"})
    monkeypatch.setattr(hardware, "_probe_encoder", fake_probe)

    detect_encoder("auto")
    detect_encoder("auto")
    detect_encoder("auto")

    assert calls == ["h264_nvenc"], "probe harus dijalankan sekali lalu di-cache"


def test_mark_unusable_disables_encoder(monkeypatch) -> None:
    monkeypatch.setattr(hardware, "list_encoders", lambda: {"h264_nvenc", "libx264"})
    monkeypatch.setattr(hardware, "_probe_encoder", lambda enc: True)

    assert detect_encoder("auto").name == EncoderChoice.NVENC
    hardware.mark_encoder_unusable("h264_nvenc")
    assert detect_encoder("auto").name == EncoderChoice.LIBX264


def test_cpu_preference_skips_probe(monkeypatch) -> None:
    def boom(enc: str) -> bool:
        raise AssertionError("probe tidak boleh dipanggil untuk preferensi cpu")

    monkeypatch.setattr(hardware, "_probe_encoder", boom)
    monkeypatch.setattr(hardware, "list_encoders", lambda: set())

    assert detect_encoder("cpu").name == EncoderChoice.LIBX264


def test_real_probe_rejects_bogus_encoder() -> None:
    """Probe sungguhan terhadap encoder yang tidak ada harus mengembalikan False."""
    if hardware._ffmpeg_bin() is None:
        pytest.skip("ffmpeg tidak tersedia")
    assert hardware._probe_encoder("h264_definitely_not_real") is False


def test_real_probe_accepts_libx264() -> None:
    if hardware._ffmpeg_bin() is None:
        pytest.skip("ffmpeg tidak tersedia")
    assert hardware._probe_encoder("libx264") is True


def test_runtime_fallback_recovers_from_hw_failure(tmp_path: Path, monkeypatch) -> None:
    """
    Kalau encoder hardware lolos probe tapi gagal saat encode nyata,
    job harus tetap selesai lewat libx264, bukan gagal.
    """
    from app.ffmpeg.ffmpeg import FFmpegRunner

    if hardware._ffmpeg_bin() is None:
        pytest.skip("ffmpeg tidak tersedia")

    src = tmp_path / "in.mp4"
    subprocess.run(
        [
            str(hardware._ffmpeg_bin()),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=15:duration=2",
            "-c:v",
            "libx264",
            str(src),
        ],
        capture_output=True,
        check=True,
    )

    # Berpura-pura ada encoder hardware yang lolos deteksi tapi tidak valid.
    monkeypatch.setattr(hardware, "list_encoders", lambda: {"h264_nvenc", "libx264"})
    monkeypatch.setattr(hardware, "_probe_encoder", lambda enc: True)

    out = tmp_path / "out.mp4"
    FFmpegRunner(hardware="nvidia").encode(
        input_path=src,
        output_path=out,
        video_bitrate_kbps=300,
        duration=2.0,
        preset="ultrafast",
    )

    assert out.exists() and out.stat().st_size > 0
