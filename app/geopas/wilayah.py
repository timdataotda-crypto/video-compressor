from __future__ import annotations

from typing import Iterable, Literal, Optional

from app.geopas.models import PaketPekerjaan, Wilayah

Level = Literal["provinsi", "kabupaten", "kecamatan"]


def _digits(kode: str) -> str:
    return "".join(ch for ch in kode if ch.isdigit())


def classify_level(item: Wilayah) -> Level:
    """Infer administrative level from BPS-style kode / parent_kode."""
    digits = _digits(item.kode)
    if digits:
        if len(digits) <= 2:
            return "provinsi"
        if len(digits) <= 4:
            return "kabupaten"
        return "kecamatan"
    if not item.parent_kode:
        return "provinsi"
    parent_digits = _digits(item.parent_kode)
    if len(parent_digits) <= 2:
        return "kabupaten"
    return "kecamatan"


def split_wilayah(items: Iterable[Wilayah]) -> dict[Level, list[Wilayah]]:
    grouped: dict[Level, list[Wilayah]] = {
        "provinsi": [],
        "kabupaten": [],
        "kecamatan": [],
    }
    for item in items:
        grouped[classify_level(item)].append(item)
    for level in grouped:
        grouped[level].sort(key=lambda w: w.nama.lower())
    return grouped


def children_of(parent: Wilayah, items: Iterable[Wilayah]) -> list[Wilayah]:
    parent_kode = parent.kode
    parent_id = str(parent.id)
    parent_digits = _digits(parent_kode)
    parent_level = classify_level(parent)
    want: Level = "kabupaten" if parent_level == "provinsi" else "kecamatan"
    out: list[Wilayah] = []
    for item in items:
        if classify_level(item) != want:
            continue
        pk = item.parent_kode
        if pk and (pk == parent_kode or pk == parent_id):
            out.append(item)
            continue
        child_digits = _digits(item.kode)
        if (
            parent_digits
            and child_digits.startswith(parent_digits)
            and len(child_digits) > len(parent_digits)
        ):
            out.append(item)
    out.sort(key=lambda w: w.nama.lower())
    return out


def filter_paket(
    items: Iterable[PaketPekerjaan],
    *,
    provinsi: Optional[Wilayah] = None,
    kabupaten: Optional[Wilayah] = None,
    kecamatan: Optional[Wilayah] = None,
) -> list[PaketPekerjaan]:
    pool = list(items)
    if kecamatan is not None:
        hit = [p for p in pool if p.wilayah_id == kecamatan.id]
        if hit:
            return _sorted_paket(hit)
        if kabupaten is None and provinsi is None:
            return []
    if kabupaten is not None:
        hit = [
            p
            for p in pool
            if p.kabupaten_id == kabupaten.id or p.wilayah_id == kabupaten.id
        ]
        if hit:
            return _sorted_paket(hit)
        if provinsi is None:
            return []
    if provinsi is not None:
        hit = [
            p
            for p in pool
            if p.provinsi_id == provinsi.id or p.wilayah_id == provinsi.id
        ]
        return _sorted_paket(hit)
    return _sorted_paket(pool)


def _sorted_paket(items: Iterable[PaketPekerjaan]) -> list[PaketPekerjaan]:
    return sorted(items, key=lambda p: p.nama.lower())
