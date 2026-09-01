from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


@dataclass(frozen=True)
class Wilayah:
    id: int
    kode: str
    parent_kode: str
    nama: str

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Wilayah | None:
        ident = _as_int(raw.get("id"))
        if ident is None:
            return None
        nama = _as_str(raw.get("nama") or raw.get("name") or raw.get("nama_wilayah"))
        if not nama:
            nama = f"Wilayah {ident}"
        return cls(
            id=ident,
            kode=_as_str(raw.get("kode")),
            parent_kode=_as_str(raw.get("parent_kode") or raw.get("parentKode")),
            nama=nama,
        )


@dataclass(frozen=True)
class PaketPekerjaan:
    id: int
    nama: str
    wilayah_id: Optional[int] = None
    provinsi_id: Optional[int] = None
    kabupaten_id: Optional[int] = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> PaketPekerjaan | None:
        ident = _as_int(raw.get("id"))
        if ident is None:
            return None
        nested = raw.get("wilayah") if isinstance(raw.get("wilayah"), dict) else {}
        nama = _as_str(
            raw.get("nama_paket")
            or raw.get("nama")
            or raw.get("no_kontrak")
            or raw.get("nama_kegiatan")
        )
        if not nama:
            nama = f"Paket {ident}"
        return cls(
            id=ident,
            nama=nama,
            wilayah_id=_as_int(raw.get("wilayah_id") or nested.get("id")),
            provinsi_id=_as_int(raw.get("provinsi_id")),
            kabupaten_id=_as_int(raw.get("kabupaten_id")),
        )
