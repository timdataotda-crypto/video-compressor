from __future__ import annotations

MB = 1024 * 1024


def calculate_video_bitrate_kbps(
    duration_sec: float,
    target_size_mb: float = 19.0,
    safety_margin: float = 0.94,
    audio_bitrate_kbps: int = 96,
) -> int:
    """
    Compute target video bitrate (kbps) for a max file size.

    usable_bytes = target_bytes * safety_margin
    total_bitrate = usable_bits / duration
    video_bitrate = total_bitrate - audio_bitrate
    """
    if duration_sec <= 0:
        raise ValueError("Durasi video harus > 0")

    target_bytes = target_size_mb * MB
    usable_bytes = target_bytes * safety_margin
    usable_bits = usable_bytes * 8
    total_bitrate_bps = usable_bits / duration_sec
    total_bitrate_kbps = total_bitrate_bps / 1000
    video_bitrate = int(total_bitrate_kbps - audio_bitrate_kbps)
    return max(video_bitrate, 50)


def calculate_retry_bitrate_kbps(
    current_bitrate_kbps: int,
    target_size_mb: float,
    actual_size_mb: float,
    retry_margin: float = 0.96,
) -> int:
    if actual_size_mb <= 0:
        raise ValueError("Ukuran aktual harus > 0")
    new_bitrate = (
        current_bitrate_kbps * (target_size_mb / actual_size_mb) * retry_margin
    )
    return max(int(new_bitrate), 50)


def bytes_to_mb(size_bytes: int) -> float:
    return size_bytes / MB


# Soft floor: below this video bitrate, quality usually collapses.
MIN_USEFUL_VIDEO_BITRATE_KBPS = 200


def is_target_realistic(
    duration_sec: float,
    target_size_mb: float,
    safety_margin: float = 0.94,
    audio_bitrate_kbps: int = 96,
    min_video_bitrate_kbps: int = MIN_USEFUL_VIDEO_BITRATE_KBPS,
) -> tuple[bool, int, str]:
    """
    Return (ok, video_bitrate_kbps, warning_message).

    Target dianggap tidak realistis jika bitrate video hasil perhitungan
    jatuh di bawah ambang kualitas minimum.
    """
    if duration_sec <= 0:
        return False, 0, "Durasi video tidak valid."

    bitrate = calculate_video_bitrate_kbps(
        duration_sec=duration_sec,
        target_size_mb=target_size_mb,
        safety_margin=safety_margin,
        audio_bitrate_kbps=audio_bitrate_kbps,
    )
    if bitrate < min_video_bitrate_kbps:
        max_duration = (
            (target_size_mb * MB * safety_margin * 8 / 1000)
            - audio_bitrate_kbps
        ) / min_video_bitrate_kbps
        return (
            False,
            bitrate,
            (
                f"Target {target_size_mb:g} MB terlalu kecil untuk "
                f"durasi {duration_sec:.0f}s (bitrate ~{bitrate} kbps). "
                f"Untuk kualitas minimal, naikkan target atau potong video "
                f"(perkiraan max durasi @ {min_video_bitrate_kbps} kbps: "
                f"~{max(0, max_duration):.0f}s)."
            ),
        )
    return True, bitrate, ""


def suggest_min_target_mb(
    duration_sec: float,
    safety_margin: float = 0.94,
    audio_bitrate_kbps: int = 96,
    min_video_bitrate_kbps: int = MIN_USEFUL_VIDEO_BITRATE_KBPS,
) -> float:
    """Minimum target MB yang masih memberi bitrate video di atas floor."""
    if duration_sec <= 0:
        return 1.0
    total_kbps = min_video_bitrate_kbps + audio_bitrate_kbps
    bits = total_kbps * 1000 * duration_sec
    bytes_needed = bits / 8 / safety_margin
    return round(bytes_needed / MB, 1)


# Floor / ceiling by output height (display pixels).
_BITRATE_BOUNDS: list[tuple[int, int, int]] = [
    # max_height, floor_kbps, ceiling_kbps
    (540, 120, 2_500),
    (720, 250, 5_000),
    (1080, 400, 10_000),
    (1440, 700, 16_000),
    (2160, 1_000, 30_000),
]


def bitrate_bounds_for_height(height: int) -> tuple[int, int]:
    for max_h, floor, ceiling in _BITRATE_BOUNDS:
        if height <= max_h:
            return floor, ceiling
    return 1_200, 40_000


def clamp_bitrate_for_resolution(
    bitrate_kbps: int,
    width: int,
    height: int,
) -> int:
    """Clamp ABR bitrate to a sane range for the output resolution."""
    _ = width
    floor, ceiling = bitrate_bounds_for_height(max(height, 1))
    return max(floor, min(int(bitrate_kbps), ceiling))


def estimate_crf_ladder(start: int = 23) -> list[int]:
    """CRF values from better→smaller for size fallback."""
    values = []
    crf = start
    while crf <= 40:
        values.append(crf)
        crf += 2
    if 40 not in values:
        values.append(40)
    return values

