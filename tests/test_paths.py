from __future__ import annotations

from pathlib import Path

from app.utils.paths import _DEFAULTS, map_output_path


def test_preserve_structure(tmp_path: Path) -> None:
    source_root = tmp_path / "DRONE"
    src = source_root / "DAY_01" / "DJI_001.mov"
    out_root = tmp_path / "OUT"
    mapped = map_output_path(source_root, src, out_root, preserve_structure=True)
    assert mapped == out_root / "DAY_01" / "DJI_001.mp4"


def test_preserve_structure_with_symlink_root(tmp_path: Path) -> None:
    """macOS /tmp -> /private/tmp style mismatch must still preserve folders."""
    real_root = (tmp_path / "real_drone").resolve()
    (real_root / "DAY_01").mkdir(parents=True)
    src = real_root / "DAY_01" / "DJI_001.mp4"
    src.write_bytes(b"x")
    # Pass unresolved-looking paths (same as CLI often does)
    mapped = map_output_path(
        Path(str(real_root)),
        src.resolve(),
        tmp_path / "OUT",
        preserve_structure=True,
    )
    assert mapped.name == "DJI_001.mp4"
    assert mapped.parent.name == "DAY_01"


def test_flat_output(tmp_path: Path) -> None:
    source_root = tmp_path / "DRONE"
    src = source_root / "DAY_01" / "DJI_001.mov"
    out_root = tmp_path / "OUT"
    mapped = map_output_path(source_root, src, out_root, preserve_structure=False)
    assert mapped == out_root / "DJI_001.mp4"


def test_default_output_destination_is_geopas() -> None:
    assert _DEFAULTS["output_destination"] == "geopas"
