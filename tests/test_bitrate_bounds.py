from __future__ import annotations

from app.core.bitrate import (
    bitrate_bounds_for_height,
    clamp_bitrate_for_resolution,
    estimate_crf_ladder,
)


def test_bounds_by_height() -> None:
    assert bitrate_bounds_for_height(540) == (120, 2500)
    assert bitrate_bounds_for_height(720)[0] == 250
    assert bitrate_bounds_for_height(1080)[0] == 400


def test_clamp_bitrate() -> None:
    assert clamp_bitrate_for_resolution(50, 1280, 720) == 250
    assert clamp_bitrate_for_resolution(99999, 1920, 1080) == 10_000
    assert clamp_bitrate_for_resolution(2000, 1280, 720) == 2000


def test_crf_ladder() -> None:
    ladder = estimate_crf_ladder(26)
    assert ladder[0] == 26
    assert ladder[-1] == 40
    assert ladder == sorted(ladder)
