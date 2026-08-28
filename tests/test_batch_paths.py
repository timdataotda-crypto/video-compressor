from __future__ import annotations

from pathlib import Path

from app.utils.batch_paths import common_path, infer_batch_roots


def test_common_path(tmp_path: Path) -> None:
    a = tmp_path / "DRONE" / "DAY_01" / "a.mp4"
    b = tmp_path / "DRONE" / "DAY_02" / "b.mp4"
    a.parent.mkdir(parents=True)
    b.parent.mkdir(parents=True)
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    assert common_path([a, b]) == (tmp_path / "DRONE").resolve()


def test_infer_batch_roots(tmp_path: Path) -> None:
    src1 = tmp_path / "SRC" / "DAY_01" / "a.mp4"
    src2 = tmp_path / "SRC" / "DAY_02" / "b.mp4"
    out1 = tmp_path / "OUT" / "DAY_01" / "a.mp4"
    out2 = tmp_path / "OUT" / "DAY_02" / "b.mp4"
    for p in (src1, src2, out1, out2):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")

    src_root, out_root = infer_batch_roots(
        [str(src1), str(src2)],
        [str(out1), str(out2)],
    )
    assert Path(src_root) == (tmp_path / "SRC").resolve()
    assert Path(out_root) == (tmp_path / "OUT").resolve()
