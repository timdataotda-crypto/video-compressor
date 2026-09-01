from __future__ import annotations

import errno
import http.client
import json
import secrets
import ssl
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from app.geopas.models import PaketPekerjaan, Wilayah

_MAX_VIDEO_BYTES = 50 * 1024 * 1024
_PAGE_SIZE = 500


class GeopasError(RuntimeError):
    """Gagal memanggil API Geopas."""


def extract_token(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    for key in ("token", "access_token"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("token", "access_token"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def extract_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
    return []


def extract_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "msg"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        errors = payload.get("errors")
        if isinstance(errors, dict):
            parts = []
            for v in errors.values():
                if isinstance(v, list) and v:
                    parts.append(str(v[0]))
                elif v:
                    parts.append(str(v))
            if parts:
                return "; ".join(parts)
        data = payload.get("data")
        if isinstance(data, dict):
            msg = data.get("message")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
    return fallback


class GeopasClient:
    def __init__(self, base_url: str, timeout: float = 45.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token: Optional[str] = None
        self._email = ""
        self._password = ""

    def login(self, email: str, password: str) -> dict[str, Any]:
        self._email = email
        self._password = password
        payload = self._request(
            "POST",
            "auth/login",
            json_body={"email": email, "password": password},
            auth=False,
        )
        token = extract_token(payload)
        if not token:
            raise GeopasError("Login berhasil tetapi token JWT tidak ditemukan.")
        self.token = token
        return payload if isinstance(payload, dict) else {}

    def current_user(self) -> dict[str, Any]:
        payload = self._request("GET", "auth/user")
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                return data
            return payload
        return {}

    def ensure_auth(self) -> None:
        if not self._email or not self._password:
            return
        try:
            self.current_user()
        except GeopasError:
            self.login(self._email, self._password)

    def list_wilayah(self, parent_kode: str = "null") -> list[Wilayah]:
        """Ambil anak langsung. `parent_kode=null` = 38 provinsi, bukan 91 ribu desa."""
        rows = self._list_filtered("wilayah", {"parent_kode": parent_kode})
        out: list[Wilayah] = []
        for raw in rows:
            item = Wilayah.from_api(raw)
            if item is not None:
                out.append(item)
        return out

    def list_paket_pekerjaan(
        self,
        *,
        wilayah_id: Optional[int] = None,
        provinsi_id: Optional[int] = None,
        kabupaten_id: Optional[int] = None,
        nama: Optional[str] = None,
    ) -> list[PaketPekerjaan]:
        extra: dict[str, str] = {}
        # API meng-AND filter. Jangan kirim wilayah_id bersama kabupaten_id —
        # itu membuat hasil kosong. Satu kunci geografis saja.
        if kabupaten_id is not None:
            extra["kabupaten_id"] = str(kabupaten_id)
        elif wilayah_id is not None:
            extra["wilayah_id"] = str(wilayah_id)
        elif provinsi_id is not None:
            extra["provinsi_id"] = str(provinsi_id)
        query = (nama or "").strip()
        if query:
            extra["nama"] = query
        if not extra:
            return []
        rows = self._list_filtered("paket_pekerjaan", extra)
        out: list[PaketPekerjaan] = []
        for raw in rows:
            item = PaketPekerjaan.from_api(raw)
            if item is not None:
                out.append(item)
        if query:
            needle = query.lower()
            out = [
                p
                for p in out
                if needle in p.nama.lower() or needle in str(p.id)
            ]
        return out

    def upload_video(self, paket_id: int, video_path: Path) -> Any:
        path = Path(video_path)
        if not path.is_file():
            raise GeopasError(f"File hasil compress tidak ditemukan: {path}")
        file_size = path.stat().st_size
        if file_size > _MAX_VIDEO_BYTES:
            mb = file_size / (1024 * 1024)
            raise GeopasError(
                f"File {path.name} ({mb:.1f} MB) melebihi batas unggah Geopas 50 MB."
            )
        self.ensure_auth()
        last_error: Optional[GeopasError] = None
        # Kolom & folder storage Geopas adalah `file_video` (bukan `video`).
        # Field `video` hanya cadangan jika API menolak nama field baru.
        for field in ("file_video", "video"):
            body, content_type = _multipart_bytes(path, field=field)
            try:
                return self._post_bytes(
                    f"paket_pekerjaan/{paket_id}",
                    body=body,
                    content_type=content_type,
                    extra_headers={"X-HTTP-Method-Override": "PUT"},
                    timeout=max(self.timeout, 300.0),
                )
            except GeopasError as exc:
                last_error = self._wrap_upload_error(exc, path, len(body))
                if not _is_retryable_upload(exc):
                    raise last_error from exc
        assert last_error is not None
        raise last_error

    def _wrap_upload_error(
        self, exc: GeopasError, path: Path, body_size: int
    ) -> GeopasError:
        message = str(exc)
        mb = body_size / (1024 * 1024)
        if _is_size_or_pipe_error(message):
            return GeopasError(
                f"{message} File lokal {path.name} tetap aman "
                f"(payload unggah {mb:.1f} MB). Server menutup koneksi di tengah POST "
                "(umumnya Nginx client_max_body_size / PHP post_max_size < 20 MB). "
                "Minta admin Geopas menaikkan limit ≥ 50 MB."
            )
        if "failed to upload" in message.lower():
            return GeopasError(
                f"{message} File lokal {path.name} tetap aman "
                f"(payload {mb:.1f} MB). Request sudah diterima Laravel — "
                "post_max_size / LimitRequestBody bukan penyebabnya. "
                "PHP Apache masih menolak file lewat upload_max_filesize "
                "(default 2M; 2.10 MiB ke atas gagal). "
                "Set upload_max_filesize=50M di php.ini yang dipakai Apache/php-fpm, "
                "lalu restart php-fpm dan apache2. Ubah post_max_size saja tidak cukup."
            )
        return exc

    def _list_filtered(
        self,
        path: str,
        extra: dict[str, str],
    ) -> list[dict[str, Any]]:
        query = {"limit": str(_PAGE_SIZE), **extra}
        payload = self._request("GET", path, query=query)
        rows = extract_list(payload)
        if len(rows) < _PAGE_SIZE:
            return rows
        return self._list_by_skip(path, extra)

    def _list_by_skip(
        self,
        path: str,
        extra: dict[str, str],
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        seen: set[Any] = set()
        page_size = _PAGE_SIZE
        skip = 0
        max_rows = 2_000
        while skip < max_rows:
            query = {"limit": str(page_size), "skip": str(skip), **extra}
            payload = self._request("GET", path, query=query)
            rows = extract_list(payload)
            if not rows:
                break
            added = _extend_unique(collected, seen, rows)
            if added == 0:
                break
            if len(rows) < page_size:
                break
            skip += page_size
        return collected

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
        query: Optional[dict[str, str]] = None,
        extra_headers: Optional[dict[str, str]] = None,
        auth: bool = True,
        timeout: Optional[float] = None,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {"Accept": "application/json"}
        data: Any = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth:
            if not self.token:
                raise GeopasError("Belum login ke Geopas.")
            headers["Authorization"] = f"Bearer {self.token}"
        if extra_headers:
            headers.update(extra_headers)
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read()
                status = getattr(resp, "status", 200)
        except HTTPError as exc:
            raw = exc.read()
            payload = _decode_json(raw)
            raise GeopasError(
                extract_message(payload, f"HTTP {exc.code} pada {path}")
            ) from exc
        except URLError as exc:
            raise GeopasError(f"Tidak dapat terhubung ke Geopas: {exc.reason}") from exc
        payload = _decode_json(raw)
        if isinstance(payload, dict) and payload.get("success") is False:
            raise GeopasError(extract_message(payload, f"Permintaan {path} ditolak."))
        if status >= 400:
            raise GeopasError(extract_message(payload, f"HTTP {status} pada {path}"))
        return payload

    def _post_bytes(
        self,
        path: str,
        *,
        body: bytes,
        content_type: str,
        extra_headers: Optional[dict[str, str]] = None,
        timeout: float = 300.0,
    ) -> Any:
        if not self.token:
            raise GeopasError("Belum login ke Geopas.")
        parsed = urlparse(f"{self.base_url}/{path.lstrip('/')}")
        host = parsed.hostname or ""
        port = parsed.port
        conn_path = parsed.path or "/"
        if parsed.query:
            conn_path = f"{conn_path}?{parsed.query}"
        headers = {
            "Accept": "application/json",
            "Host": host,
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "Authorization": f"Bearer {self.token}",
            "Connection": "close",
        }
        if extra_headers:
            headers.update(extra_headers)
        if parsed.scheme == "https":
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                host,
                port or 443,
                timeout=timeout,
                context=ssl.create_default_context(),
            )
        else:
            conn = http.client.HTTPConnection(host, port or 80, timeout=timeout)
        try:
            conn.request(
                "POST",
                conn_path,
                body=body,
                headers=headers,
                encode_chunked=False,
            )
            resp = conn.getresponse()
            raw = resp.read()
            status = resp.status
        except ConnectionResetError as exc:
            raise GeopasError("Broken pipe: server menutup koneksi saat unggah.") from exc
        except BrokenPipeError as exc:
            raise GeopasError("Broken pipe: server menutup koneksi saat unggah.") from exc
        except OSError as exc:
            if getattr(exc, "errno", None) == errno.EPIPE:
                raise GeopasError("Broken pipe: server menutup koneksi saat unggah.") from exc
            raise GeopasError(f"Tidak dapat terhubung ke Geopas: {exc}") from exc
        finally:
            conn.close()
        payload = _decode_json(raw)
        if isinstance(payload, dict) and payload.get("success") is False:
            raise GeopasError(extract_message(payload, f"Permintaan {path} ditolak."))
        if status >= 400:
            raise GeopasError(extract_message(payload, f"HTTP {status} pada {path}"))
        return payload


def _extend_unique(
    collected: list[dict[str, Any]],
    seen: set[Any],
    rows: list[dict[str, Any]],
) -> int:
    added = 0
    for row in rows:
        ident = row.get("id")
        key = ident if ident is not None else json.dumps(row, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        collected.append(row)
        added += 1
    return added


def _decode_json(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        text = raw.decode("utf-8", errors="replace")[:300]
        return {"message": text}


def _multipart_bytes(video: Path, field: str) -> tuple[bytes, str]:
    boundary = "----DroneCompressor" + secrets.token_hex(16)
    filename = video.name.replace('"', "_")
    parts = bytearray()
    parts.extend(f"--{boundary}\r\n".encode("ascii"))
    parts.extend(b'Content-Disposition: form-data; name="_method"\r\n\r\nPUT\r\n')
    parts.extend(f"--{boundary}\r\n".encode("ascii"))
    parts.extend(
        (
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: video/mp4\r\n\r\n"
        ).encode("utf-8")
    )
    parts.extend(video.read_bytes())
    parts.extend(b"\r\n")
    parts.extend(f"--{boundary}--\r\n".encode("ascii"))
    return bytes(parts), f"multipart/form-data; boundary={boundary}"


def _is_size_or_pipe_error(message: str) -> bool:
    msg = message.lower()
    return any(
        token in msg
        for token in (
            "broken pipe",
            "too large",
            "413",
            "client_max_body",
            "post_max_size",
            "request entity too large",
        )
    )


def _is_retryable_upload(exc: GeopasError) -> bool:
    message = str(exc)
    if _is_size_or_pipe_error(message):
        return False
    if "tidak dapat terhubung" in message.lower():
        return False
    return True
