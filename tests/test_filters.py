from __future__ import annotations

from app.core.filters import (
    build_vf_filter,
    display_dimensions,
    normalize_rotation,
    rotation_filters,
)


def test_normalize_rotation() -> None:
    assert normalize_rotation(90) == 90
    assert normalize_rotation(-90) == 270
    assert normalize_rotation(180) == 180


def test_display_dimensions_swap_on_90() -> None:
    assert display_dimensions(1920, 1080, 90) == (1080, 1920)
    assert display_dimensions(1920, 1080, 0) == (1920, 1080)


def test_rotation_filters() -> None:
    assert rotation_filters(90) == ["transpose=1"]
    assert rotation_filters(270) == ["transpose=2"]
    assert rotation_filters(0) == []


def test_build_vf_includes_transpose_and_scale() -> None:
    # Low bitrate forces downscale on display height (1920 after 90° rot of 1080p)
    geo = build_vf_filter(1920, 1080, 90, video_bitrate_kbps=800, mode="auto")
    assert geo.vf_filter is not None
    assert "transpose=1" in geo.vf_filter
    assert "scale=" in geo.vf_filter
    assert geo.display_height <= 720
