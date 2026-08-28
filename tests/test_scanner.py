from __future__ import annotations

from pathlib import Path

from app.core.scanner import scan_videos


def test_scan_videos_recursive(tmp_path: Path) -> None:
    day1 = tmp_path / "DAY_01"
    day1.mkdir()
    (day1 / "DJI_001.mp4").write_bytes(b"x")
    (day1 / "DJI_002.MOV").write_bytes(b"x")
    (day1 / "notes.txt").write_text("no")
    (day1 / ".tmp.mp4").write_bytes(b"x")
    nested = day1 / "sub"
    nested.mkdir()
    (nested / "clip.mkv").write_bytes(b"x")

    found = scan_videos(tmp_path, recursive=True)
    names = sorted(p.name for p in found)
    assert names == ["DJI_001.mp4", "DJI_002.MOV", "clip.mkv"]


def test_scan_non_recursive(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.mp4").write_bytes(b"x")
    found = scan_videos(tmp_path, recursive=False)
    assert [p.name for p in found] == ["a.mp4"]
