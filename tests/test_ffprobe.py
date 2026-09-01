from __future__ import annotations

from pathlib import Path

import pytest

from app.ffmpeg.ffprobe import FFprobeError, _describe_probe_failure, probe_video
from app.utils.deps import check_ffmpeg_deps


def test_describe_moov_missing() -> None:
    msg = _describe_probe_failure(
        "clip.MP4",
        "[mov] moov atom not found\nclip.MP4: Invalid data found when processing input",
    )
    assert "bukan MP4 utuh" in msg
    assert "Salin ulang" in msg


def test_describe_generic_stderr() -> None:
    msg = _describe_probe_failure("clip.MP4", "Permission denied")
    assert "Permission denied" in msg


@pytest.mark.skipif(not check_ffmpeg_deps().ok, reason="ffprobe tidak tersedia")
def test_probe_truncated_mp4(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64)
    with pytest.raises(FFprobeError) as exc:
        probe_video(broken)
    assert "bukan MP4 utuh" in str(exc.value) or "FFprobe gagal" in str(exc.value)
