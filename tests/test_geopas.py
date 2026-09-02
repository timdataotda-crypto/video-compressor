from __future__ import annotations

import json
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError

from app.geopas.client import (
    GeopasClient,
    GeopasError,
    _connect_error_message,
    _multipart_bytes,
    _ssl_context,
    extract_list,
    extract_token,
)
from app.geopas.models import PaketPekerjaan, Wilayah
from app.geopas.wilayah import children_of, classify_level, filter_paket, split_wilayah


def test_extract_token_shapes() -> None:
    assert extract_token({"token": "abc"}) == "abc"
    assert extract_token({"access_token": "xyz"}) == "xyz"
    assert extract_token({"success": True, "data": {"token": "jwt"}}) == "jwt"
    assert extract_token({"success": True, "data": []}) is None


def test_extract_list_paginator() -> None:
    rows = extract_list({"success": True, "data": [{"id": 1}, {"id": 2}]})
    assert [r["id"] for r in rows] == [1, 2]
    nested = extract_list({"data": {"data": [{"id": 9}], "current_page": 1}})
    assert nested[0]["id"] == 9


def test_classify_and_children() -> None:
    prov = Wilayah(id=1, kode="13", parent_kode="", nama="Sumatera Barat")
    kab = Wilayah(id=2, kode="1301", parent_kode="13", nama="Kepulauan Mentawai")
    kec = Wilayah(id=3, kode="130101", parent_kode="1301", nama="Siberut Selatan")
    assert classify_level(prov) == "provinsi"
    assert classify_level(kab) == "kabupaten"
    assert classify_level(kec) == "kecamatan"
    grouped = split_wilayah([kec, kab, prov])
    assert grouped["provinsi"] == [prov]
    assert children_of(prov, [prov, kab, kec]) == [kab]
    assert children_of(kab, [prov, kab, kec]) == [kec]


def test_filter_paket_falls_back_to_kabupaten() -> None:
    prov = Wilayah(id=1, kode="13", parent_kode="", nama="Sumbar")
    kab = Wilayah(id=2, kode="1301", parent_kode="13", nama="Mentawai")
    kec = Wilayah(id=3, kode="130101", parent_kode="1301", nama="Siberut")
    paket = PaketPekerjaan(
        id=10,
        nama="Rehab Jalan",
        wilayah_id=2,
        provinsi_id=1,
        kabupaten_id=2,
    )
    assert filter_paket([paket], kecamatan=kec) == []
    assert filter_paket([paket], kabupaten=kab, kecamatan=kec) == [paket]
    assert filter_paket([paket], provinsi=prov) == [paket]


def test_list_follows_skip_pages(monkeypatch) -> None:
    pages = {
        "0": [
            {"id": 1, "kode": "11", "parent_kode": None, "nama": "Aceh"},
            {"id": 2, "kode": "1101", "parent_kode": "11", "nama": "Simeulue"},
        ],
        "2": [
            {"id": 3, "kode": "12", "parent_kode": None, "nama": "Sumatera Utara"},
        ],
    }

    class FakeResp:
        status = 200

        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=None, **_kwargs):
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(req.full_url).query)
        skip = (qs.get("skip") or ["0"])[0]
        rows = pages.get(skip, [])
        return FakeResp(json.dumps({"success": True, "data": rows}).encode())

    monkeypatch.setattr("app.geopas.client.urlopen", fake_urlopen)
    monkeypatch.setattr("app.geopas.client._PAGE_SIZE", 2)
    import app.geopas.client as client_mod

    client_mod._PAGE_SIZE = 2
    client = GeopasClient("https://geopas.example/api")
    client.token = "jwt"
    items = client.list_wilayah()
    names = [w.nama for w in items]
    assert "Aceh" in names
    assert "Sumatera Utara" in names
    assert len(items) == 3


def test_paket_query_uses_single_geo_filter(monkeypatch) -> None:
    seen: list[str] = []

    class FakeResp:
        status = 200

        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=None, **_kwargs):
        seen.append(req.full_url)
        return FakeResp(
            b'{"success":true,"data":[{"id":161,"nama":"Pasar Samalanga",'
            b'"kabupaten_id":4405,"provinsi_id":1}]}'
        )

    monkeypatch.setattr("app.geopas.client.urlopen", fake_urlopen)
    client = GeopasClient("https://geopas.example/api")
    client.token = "jwt"
    items = client.list_paket_pekerjaan(kabupaten_id=4405, wilayah_id=4405)
    assert len(items) == 1
    url = seen[0]
    assert "kabupaten_id=4405" in url
    assert "wilayah_id=" not in url


def test_login_and_list(monkeypatch) -> None:
    calls: list[str] = []

    class FakeResp:
        status = 200

        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=None, **_kwargs):
        url = req.full_url
        calls.append(url)
        if url.endswith("/auth/login"):
            return FakeResp(b'{"success":true,"token":"jwt-1"}')
        if "/wilayah" in url:
            return FakeResp(
                b'{"success":true,"data":[{"id":1,"kode":"13","parent_kode":null,'
                b'"nama":"Sumatera Barat"}]}'
            )
        raise AssertionError(url)

    monkeypatch.setattr("app.geopas.client.urlopen", fake_urlopen)
    client = GeopasClient("https://geopas.example/api")
    client.login("demo@admin", "secret")
    assert client.token == "jwt-1"
    items = client.list_wilayah()
    assert items[0].nama == "Sumatera Barat"
    assert any("/auth/login" in c for c in calls)


def test_http_error_uses_message(monkeypatch) -> None:
    class Err(HTTPError):
        def __init__(self) -> None:
            super().__init__(
                url="https://x/api/auth/login",
                code=401,
                msg="Unauthorized",
                hdrs=None,
                fp=None,
            )

        def read(self) -> bytes:
            return b'{"success":false,"message":"Email atau password salah"}'

    def fake_urlopen(req, timeout=None, **_kwargs):
        raise Err()

    monkeypatch.setattr("app.geopas.client.urlopen", fake_urlopen)
    client = GeopasClient("https://geopas.example/api")
    try:
        client.login("a", "b")
        raise AssertionError("expected GeopasError")
    except GeopasError as exc:
        assert "password" in str(exc).lower() or "salah" in str(exc).lower()


def test_multipart_bytes_includes_put_and_field(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"abc123")
    body, ctype = _multipart_bytes(video, "file_video")
    assert b'name="_method"' in body
    assert b"PUT" in body
    assert b'name="file_video"' in body
    assert b"filename=\"clip.mp4\"" in body
    assert b"abc123" in body
    assert ctype.startswith("multipart/form-data; boundary=")


def test_upload_maps_broken_pipe_to_server_limit(tmp_path: Path) -> None:
    client = GeopasClient("https://geopas.example/api")
    client.token = "jwt"
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"data")

    def boom(*_args: object, **_kwargs: object) -> dict:
        raise GeopasError("Broken pipe: server menutup koneksi saat unggah.")

    client._post_bytes = boom  # type: ignore[method-assign]
    try:
        client.upload_video(1, video)
        raise AssertionError("expected GeopasError")
    except GeopasError as extra:
        text = str(extra)
        assert "aman" in text
        assert "50 MB" in text


def test_upload_maps_php_file_failed(tmp_path: Path) -> None:
    client = GeopasClient("https://geopas.example/api")
    client.token = "jwt"
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"data")

    def boom(*_args: object, **_kwargs: object) -> dict:
        raise GeopasError("The file video failed to upload.")

    client._post_bytes = boom  # type: ignore[method-assign]
    try:
        client.upload_video(1, video)
        raise AssertionError("expected GeopasError")
    except GeopasError as extra:
        assert "upload_max_filesize" in str(extra)


def test_upload_uses_file_video_field(tmp_path: Path) -> None:
    client = GeopasClient("https://geopas.example/api")
    client.token = "jwt"
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"data")
    fields: list[str] = []

    def fake_post(_path: str, *, body: bytes, content_type: str, **_kwargs: object) -> dict:
        if b'name="file_video"' in body:
            fields.append("file_video")
            return {"success": True}
        fields.append("video")
        raise GeopasError("unexpected video field")

    client._post_bytes = fake_post  # type: ignore[method-assign]
    payload = client.upload_video(9, video)
    assert payload == {"success": True}
    assert fields == ["file_video"]


def test_upload_falls_back_to_video_field(tmp_path: Path) -> None:
    client = GeopasClient("https://geopas.example/api")
    client.token = "jwt"
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"data")
    fields: list[str] = []

    def fake_post(_path: str, *, body: bytes, content_type: str, **_kwargs: object) -> dict:
        if b'name="file_video"' in body:
            fields.append("file_video")
            raise GeopasError("The file_video field is not allowed.")
        fields.append("video")
        return {"success": True}

    client._post_bytes = fake_post  # type: ignore[method-assign]
    payload = client.upload_video(9, video)
    assert payload == {"success": True}
    assert fields == ["file_video", "video"]


def test_upload_rejects_missing_file(tmp_path: Path) -> None:
    client = GeopasClient("https://geopas.example/api")
    client.token = "jwt"
    missing = tmp_path / "nope.mp4"
    try:
        client.upload_video(7, missing)
        raise AssertionError("expected GeopasError")
    except GeopasError as exc:
        assert "tidak ditemukan" in str(exc)


def test_upload_jobs_keeps_local_on_success(tmp_path: Path) -> None:
    from app.core.job_manager import JobManager
    from app.database.database import Database
    from app.models.job import Job, JobStatus

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"data")
    db = Database(tmp_path / "jobs.db")
    manager = JobManager(config={"workers": 1}, db=db)
    job = Job(
        source_path=str(tmp_path / "src.mp4"),
        output_path=str(video),
        status=JobStatus.COMPLETED,
        progress=100.0,
    )
    job.id = db.insert_job(job)

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[int, Path]] = []

        def upload_video(self, paket_id: int, path: Path) -> dict:
            self.calls.append((paket_id, path))
            return {"success": True}

    fake = FakeClient()
    manager.geopas_client = fake  # type: ignore[assignment]
    manager.geopas_paket_id = 88
    result = manager.upload_jobs([job])[0]
    assert result.status == JobStatus.COMPLETED
    assert fake.calls == [(88, video)]
    assert video.is_file()


def test_upload_jobs_uses_job_paket_id(tmp_path: Path) -> None:
    from app.core.job_manager import JobManager
    from app.database.database import Database
    from app.models.job import Job, JobStatus

    video_a = tmp_path / "a.mp4"
    video_b = tmp_path / "b.mp4"
    video_a.write_bytes(b"a")
    video_b.write_bytes(b"b")
    db = Database(tmp_path / "jobs.db")
    manager = JobManager(config={"workers": 1}, db=db)

    def make_job(path: Path, paket_id: int, nama: str) -> Job:
        job = Job(
            source_path=str(path),
            output_path=str(path),
            status=JobStatus.COMPLETED,
            progress=100.0,
            geopas_paket_id=paket_id,
            geopas_paket_nama=nama,
            batch_source=str(tmp_path),
        )
        job.id = db.insert_job(job)
        return job

    job_a = make_job(video_a, 114, "Pasar Bintang")
    job_b = make_job(video_b, 99, "SDN 2")

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[int, Path]] = []

        def upload_video(self, paket_id: int, path: Path) -> dict:
            self.calls.append((paket_id, path))
            return {"success": True}

    fake = FakeClient()
    manager.geopas_client = fake  # type: ignore[assignment]
    manager.geopas_paket_id = 1
    manager.upload_jobs([job_a, job_b])
    assert fake.calls == [(114, video_a), (99, video_b)]


def test_upload_jobs_marks_upload_failed(tmp_path: Path) -> None:
    from app.core.job_manager import JobManager
    from app.database.database import Database
    from app.geopas.client import GeopasError
    from app.models.job import Job, JobStatus

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"data")
    db = Database(tmp_path / "jobs.db")
    manager = JobManager(config={"workers": 1}, db=db)
    job = Job(
        source_path=str(tmp_path / "src.mp4"),
        output_path=str(video),
        status=JobStatus.COMPLETED,
        progress=100.0,
    )
    job.id = db.insert_job(job)

    class FakeClient:
        def upload_video(self, paket_id: int, path: Path) -> dict:
            raise GeopasError("The POST data is too large")

    manager.geopas_client = FakeClient()  # type: ignore[assignment]
    manager.geopas_paket_id = 88
    result = manager.upload_jobs([job])[0]
    assert result.status == JobStatus.UPLOAD_FAILED
    assert video.is_file()
    assert "lokal" in result.error.lower() or "File lokal" in result.error


def test_connection_error(monkeypatch) -> None:
    def fake_urlopen(req, timeout=None, **_kwargs):
        raise URLError("timed out")

    monkeypatch.setattr("app.geopas.client.urlopen", fake_urlopen)
    client = GeopasClient("https://geopas.example/api")
    try:
        client.login("a", "b")
        raise AssertionError("expected GeopasError")
    except GeopasError as exc:
        assert "Tidak dapat terhubung" in str(exc)


def test_ssl_context_uses_bundled_ca() -> None:
    import certifi

    ctx = _ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert Path(certifi.where()).is_file()


def test_ssl_error_message() -> None:
    msg = _connect_error_message(
        URLError(ssl.SSLError("CERTIFICATE_VERIFY_FAILED"))
    )
    assert "SSL" in msg
    assert "Tidak dapat terhubung" in msg
