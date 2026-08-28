from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResolutionPlan:
    width: int
    height: int
    scale_filter: str | None
    label: str


def plan_resolution(
    width: int,
    height: int,
    video_bitrate_kbps: int,
    mode: str = "auto",
) -> ResolutionPlan:
    """
    Adaptive resolution based on target video bitrate.

    >= 5000 kbps → keep original
    2500–5000    → max 1080p
    1200–2500    → max 720p
    < 1200       → max 540p
    """
    if width <= 0 or height <= 0:
        return ResolutionPlan(0, 0, None, "unknown")

    if mode and mode.lower() not in ("auto", ""):
        caps = {
            "original": None,
            "1080p": 1080,
            "720p": 720,
            "540p": 540,
        }
        cap = caps.get(mode.lower())
        if cap is None:
            return ResolutionPlan(width, height, None, f"{width}x{height}")
        return _fit_to_max_height(width, height, cap)

    if video_bitrate_kbps >= 5000:
        return ResolutionPlan(width, height, None, f"{width}x{height}")
    if video_bitrate_kbps >= 2500:
        return _fit_to_max_height(width, height, 1080)
    if video_bitrate_kbps >= 1200:
        return _fit_to_max_height(width, height, 720)
    return _fit_to_max_height(width, height, 540)


def _fit_to_max_height(width: int, height: int, max_height: int) -> ResolutionPlan:
    if height <= max_height:
        return ResolutionPlan(width, height, None, f"{width}x{height}")

    scale = max_height / height
    new_w = _even(int(width * scale))
    new_h = _even(max_height)
    filt = f"scale={new_w}:{new_h}"
    return ResolutionPlan(new_w, new_h, filt, f"{new_w}x{new_h}")


def _even(value: int) -> int:
    return value if value % 2 == 0 else value - 1
