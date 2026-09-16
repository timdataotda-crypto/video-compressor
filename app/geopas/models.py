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
    nama_paket: str = ""
    no_kontrak: str = ""
    nama_kegiatan: str = ""
    wilayah_id: Optional[int] = None
    provinsi_id: Optional[int] = None
    kabupaten_id: Optional[int] = None

    def matches(self, query: str) -> bool:
        needle = query.strip().lower()
        if not needle:
            return True
        haystack = " ".join(
            part
            for part in (
                self.nama,
                self.nama_paket,
                self.no_kontrak,
                self.nama_kegiatan,
                str(self.id),
            )
            if part
        ).lower()
        return needle in haystack

    def display_label(self) -> str:
        return f"{self.nama} (#{self.id})"

    def tooltip(self) -> str:
        lines = [f"ID: {self.id}", f"Nama: {self.nama}"]
        if self.nama_paket and self.nama_paket != self.nama:
            lines.append(f"Nama paket: {self.nama_paket}")
        if self.no_kontrak:
            lines.append(f"No. kontrak: {self.no_kontrak}")
        if self.nama_kegiatan:
            lines.append(f"Kegiatan: {self.nama_kegiatan}")
        if self.kabupaten_id is not None:
            lines.append(f"Kabupaten ID: {self.kabupaten_id}")
        return "\n".join(lines)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> PaketPekerjaan | None:
        ident = _as_int(raw.get("id"))
        if ident is None:
            return None
        nested = raw.get("wilayah") if isinstance(raw.get("wilayah"), dict) else {}
        nama = _as_str(raw.get("nama"))
        nama_paket = _as_str(raw.get("nama_paket"))
        no_kontrak = _as_str(raw.get("no_kontrak"))
        nama_kegiatan = _as_str(raw.get("nama_kegiatan"))
        display = nama or nama_paket or no_kontrak or nama_kegiatan
        if not display:
            display = f"Paket {ident}"
        return cls(
            id=ident,
            nama=display,
            nama_paket=nama_paket,
            no_kontrak=no_kontrak,
            nama_kegiatan=nama_kegiatan,
            wilayah_id=_as_int(raw.get("wilayah_id") or nested.get("id")),
            provinsi_id=_as_int(raw.get("provinsi_id")),
            kabupaten_id=_as_int(raw.get("kabupaten_id")),
        )


@dataclass(frozen=True)
class PaketSearchResult:
    items: list[PaketPekerjaan]
    used_fallback: bool = False
    scope: str = "kabupaten"
