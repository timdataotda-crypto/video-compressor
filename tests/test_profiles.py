from __future__ import annotations

from app.core.profiles import (
    apply_quality_profile,
    match_target_preset,
    normalize_profile_key,
    parse_target_preset,
)


def test_normalize_profile() -> None:
    assert normalize_profile_key("Maximum Quality") == "maximum"
    assert normalize_profile_key("FAST") == "fast"
    assert normalize_profile_key("nope") == "balanced"


def test_apply_quality_profile_sets_preset() -> None:
    cfg = apply_quality_profile({}, "fast")
    assert cfg["preset"] == "fast"
    assert cfg["quality_profile"] == "fast"

    cfg = apply_quality_profile({}, "maximum")
    assert cfg["preset"] == "slow"


def test_target_preset_helpers() -> None:
    assert match_target_preset(19) == "19 MB"
    assert match_target_preset(19.0) == "19 MB"
    assert match_target_preset(12.5) == "Custom"
    assert parse_target_preset("19 MB") == 19.0
    assert parse_target_preset("Custom") is None
