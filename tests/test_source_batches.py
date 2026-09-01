from __future__ import annotations

from pathlib import Path

from app.core.job_manager import JobManager, batch_folder_name
from app.database.database import Database
from app.models.job import JobStatus


def test_batch_folder_name_includes_paket_id() -> None:
    name = batch_folder_name("Pasar Bintang", 114)
    assert "114" in name
    assert "/" not in name
    assert ":" not in name


def test_scan_two_sources_keeps_separate_paket(tmp_path: Path) -> None:
    src_a = tmp_path / "pasar"
    src_b = tmp_path / "sekolah"
    src_a.mkdir()
    src_b.mkdir()
    (src_a / "a.mp4").write_bytes(b"aaa")
    (src_b / "b.mp4").write_bytes(b"bbb")
    output = tmp_path / "out"
    db = Database(tmp_path / "jobs.db")
    manager = JobManager(
        config={"recursive": True, "preserve_structure": True, "skip_existing": False},
        db=db,
    )
    jobs_a = manager.scan_and_create_jobs(
        src_a,
        output,
        clear_previous=True,
        geopas_paket_id=114,
        geopas_paket_nama="Pasar Bintang",
        batch_source=str(src_a.resolve()),
        batch_label="Pasar Bintang",
    )
    jobs_b = manager.scan_and_create_jobs(
        src_b,
        output,
        clear_previous=False,
        geopas_paket_id=99,
        geopas_paket_nama="SDN 2",
        batch_source=str(src_b.resolve()),
        batch_label="SDN 2",
    )
    assert len(jobs_a) == 1
    assert len(jobs_b) == 1
    all_jobs = db.list_jobs()
    assert len(all_jobs) == 2
    by_paket = {j.geopas_paket_id: j for j in all_jobs}
    assert by_paket[114].source_path.endswith("a.mp4")
    assert by_paket[99].source_path.endswith("b.mp4")
    assert "114" in by_paket[114].output_path
    assert "99" in by_paket[99].output_path
    assert by_paket[114].geopas_paket_nama == "Pasar Bintang"


def test_delete_jobs_for_batch(tmp_path: Path) -> None:
    src_a = tmp_path / "a"
    src_b = tmp_path / "b"
    src_a.mkdir()
    src_b.mkdir()
    (src_a / "a.mp4").write_bytes(b"a")
    (src_b / "b.mp4").write_bytes(b"b")
    output = tmp_path / "out"
    db = Database(tmp_path / "jobs.db")
    manager = JobManager(
        config={"recursive": False, "preserve_structure": False, "skip_existing": False},
        db=db,
    )
    manager.scan_and_create_jobs(
        src_a,
        output,
        clear_previous=True,
        geopas_paket_id=1,
        geopas_paket_nama="A",
        batch_source=str(src_a.resolve()),
        batch_label="A",
    )
    manager.scan_and_create_jobs(
        src_b,
        output,
        clear_previous=False,
        geopas_paket_id=2,
        geopas_paket_nama="B",
        batch_source=str(src_b.resolve()),
        batch_label="B",
    )
    removed = db.delete_jobs_for_batch(str(src_a.resolve()), 1)
    assert removed == 1
    left = db.list_jobs()
    assert len(left) == 1
    assert left[0].geopas_paket_id == 2
    assert left[0].status == JobStatus.PENDING
