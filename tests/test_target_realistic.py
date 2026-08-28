from __future__ import annotations

from app.core.bitrate import (
    is_target_realistic,
    suggest_min_target_mb,
)


def test_realistic_short_clip() -> None:
    ok, bitrate, msg = is_target_realistic(60, 19)
    assert ok is True
    assert bitrate > 200
    assert msg == ""


def test_unrealistic_long_clip() -> None:
    # 30 menit ke 5 MB → bitrate terlalu rendah
    ok, bitrate, msg = is_target_realistic(1800, 5)
    assert ok is False
    assert bitrate < 200
    assert "terlalu kecil" in msg


def test_suggest_min_target() -> None:
    suggested = suggest_min_target_mb(600)
    assert suggested >= 19
