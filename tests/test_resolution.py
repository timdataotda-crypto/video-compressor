from __future__ import annotations

from app.core.resolution import plan_resolution


def test_keep_4k_high_bitrate() -> None:
    plan = plan_resolution(3840, 2160, 6000)
    assert plan.scale_filter is None
    assert plan.width == 3840


def test_downscale_to_1080() -> None:
    plan = plan_resolution(3840, 2160, 3000)
    assert plan.height == 1080
    assert plan.scale_filter is not None
    assert plan.width % 2 == 0


def test_downscale_to_720() -> None:
    plan = plan_resolution(1920, 1080, 1500)
    assert plan.height == 720


def test_downscale_to_540() -> None:
    plan = plan_resolution(1920, 1080, 800)
    assert plan.height == 540


def test_already_small() -> None:
    plan = plan_resolution(1280, 720, 1500)
    assert plan.scale_filter is None
