from __future__ import annotations

from dataclasses import dataclass


TARGET_PRESETS_MB = (5, 10, 15, 19, 25, 50)


@dataclass(frozen=True)
class QualityProfile:
    key: str
    label: str
    ffmpeg_preset: str
    two_pass: bool
    resolution_mode: str
    description: str


PROFILES: dict[str, QualityProfile] = {
    "fast": QualityProfile(
        key="fast",
        label="Fast",
        ffmpeg_preset="fast",
        two_pass=False,
        resolution_mode="auto",
        description="1-pass, cepat untuk batch besar",
    ),
    "balanced": QualityProfile(
        key="balanced",
        label="Balanced",
        ffmpeg_preset="medium",
        two_pass=True,
        resolution_mode="auto",
        description="2-pass + adaptive resolution (default)",
    ),
    "maximum": QualityProfile(
        key="maximum",
        label="Maximum Quality",
        ffmpeg_preset="slow",
        two_pass=True,
        resolution_mode="auto",
        description="2-pass, preset slow, kualitas terbaik",
    ),
}


def normalize_profile_key(value: str | None) -> str:
    key = (value or "balanced").strip().lower()
    aliases = {
        "maximum quality": "maximum",
        "max": "maximum",
        "balance": "balanced",
    }
    key = aliases.get(key, key)
    return key if key in PROFILES else "balanced"


def apply_quality_profile(config: dict, profile_key: str | None = None) -> dict:
    """Return config updated with encoding knobs for the selected profile."""
    cfg = dict(config)
    key = normalize_profile_key(profile_key or cfg.get("quality_profile"))
    profile = PROFILES[key]
    cfg["quality_profile"] = key
    cfg["preset"] = profile.ffmpeg_preset
    cfg["resolution_mode"] = profile.resolution_mode
    return cfg


def profile_labels() -> list[str]:
    return [p.label for p in PROFILES.values()]


def profile_key_from_label(label: str) -> str:
    for key, profile in PROFILES.items():
        if profile.label == label:
            return key
    return normalize_profile_key(label)


def match_target_preset(value_mb: float) -> str:
    """Return combo label for a target size, or Custom."""
    for preset in TARGET_PRESETS_MB:
        if abs(float(value_mb) - float(preset)) < 0.01:
            return f"{preset} MB"
    return "Custom"


def parse_target_preset(label: str) -> float | None:
    """Return MB value for preset label, or None if Custom."""
    text = label.strip().lower()
    if text == "custom":
        return None
    if text.endswith(" mb"):
        text = text[:-3].strip()
    try:
        return float(text)
    except ValueError:
        return None
