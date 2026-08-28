from __future__ import annotations

from dataclasses import dataclass

from app.core.resolution import plan_resolution


def _even(value: int) -> int:
    return value if value % 2 == 0 else value - 1


@dataclass
class EncodeGeometry:
    """Display-aware width/height after applying rotation metadata."""

    storage_width: int
    storage_height: int
    display_width: int
    display_height: int
    rotation: int
    vf_filter: str | None
    label: str


def normalize_rotation(rotation: int) -> int:
    """Normalize to {0, 90, 180, 270}."""
    rot = int(rotation) % 360
    if rot < 0:
        rot += 360
    # Snap near values
    candidates = [0, 90, 180, 270]
    return min(candidates, key=lambda c: min(abs(c - rot), 360 - abs(c - rot)))


def display_dimensions(width: int, height: int, rotation: int) -> tuple[int, int]:
    rot = normalize_rotation(rotation)
    if rot in (90, 270):
        return height, width
    return width, height


def rotation_filters(rotation: int) -> list[str]:
    rot = normalize_rotation(rotation)
    if rot == 90:
        return ["transpose=1"]  # 90° clockwise
    if rot == 270:
        return ["transpose=2"]  # 90° counter-clockwise
    if rot == 180:
        return ["transpose=1", "transpose=1"]
    return []


def build_vf_filter(
    width: int,
    height: int,
    rotation: int,
    video_bitrate_kbps: int,
    mode: str = "auto",
) -> EncodeGeometry:
    """
    Plan scale + rotation filters.

    Resolution is planned against *display* dimensions so portrait drone
    clips are capped correctly after transpose.
    """
    disp_w, disp_h = display_dimensions(width, height, rotation)
    plan = plan_resolution(disp_w, disp_h, video_bitrate_kbps, mode=mode)

    filters = rotation_filters(rotation)
    if plan.scale_filter:
        # After transpose, scale to planned display size
        filters.append(f"scale={plan.width}:{plan.height}")
    elif plan.width and plan.height and (plan.width != disp_w or plan.height != disp_h):
        filters.append(f"scale={_even(plan.width)}:{_even(plan.height)}")

    vf = ",".join(filters) if filters else None
    label = plan.label
    if normalize_rotation(rotation) != 0:
        label = f"{label} rot{normalize_rotation(rotation)}"

    return EncodeGeometry(
        storage_width=width,
        storage_height=height,
        display_width=plan.width or disp_w,
        display_height=plan.height or disp_h,
        rotation=normalize_rotation(rotation),
        vf_filter=vf,
        label=label,
    )
