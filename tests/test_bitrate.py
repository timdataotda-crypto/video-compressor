from __future__ import annotations

from app.core.bitrate import (
    calculate_retry_bitrate_kbps,
    calculate_video_bitrate_kbps,
)


def test_bitrate_60s_19mb() -> None:
    kbps = calculate_video_bitrate_kbps(
        duration_sec=60,
        target_size_mb=19,
        safety_margin=0.94,
        audio_bitrate_kbps=96,
    )
    # ~19MB * 0.94 * 8 / 60 / 1000 - 96 ≈ 2400-ish
    assert 2000 < kbps < 2800


def test_retry_bitrate_reduces() -> None:
    new_b = calculate_retry_bitrate_kbps(
        current_bitrate_kbps=2500,
        target_size_mb=19,
        actual_size_mb=19.8,
        retry_margin=0.96,
    )
    assert new_b < 2500
    assert new_b > 2000


def test_short_duration_minimum() -> None:
    kbps = calculate_video_bitrate_kbps(duration_sec=0.01, target_size_mb=19)
    assert kbps >= 50
