from __future__ import annotations

from pathlib import Path

from app.core.validator import validate_size


def test_validate_under_target(tmp_path: Path) -> None:
    f = tmp_path / "out.mp4"
    f.write_bytes(b"0" * (10 * 1024 * 1024))
    ok, actual = validate_size(f, 19)
    assert ok is True
    assert 9.9 < actual < 10.1


def test_validate_over_target(tmp_path: Path) -> None:
    f = tmp_path / "out.mp4"
    f.write_bytes(b"0" * (20 * 1024 * 1024))
    ok, actual = validate_size(f, 19)
    assert ok is False
    assert actual > 19
