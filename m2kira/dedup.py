"""Muhtemel kopya ilan tespiti: aynı daire farklı sitelerde / farklı ilan numaralarıyla olabilir."""
from __future__ import annotations

from typing import Any, Iterable, Optional

from .textnorm import fold


def _close(a: Optional[int], b: Optional[int], tol_abs: int = 0, tol_rel: float = 0.0) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(tol_abs, tol_rel * max(a, b))


def is_probable_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """a/b: Listing.to_dict() veya DB satırı."""
    if a.get("id") == b.get("id"):
        return False
    if a.get("rooms") and b.get("rooms") and a["rooms"] != b["rooms"]:
        return False
    if not _close(a.get("price"), b.get("price"), tol_rel=0.02):
        return False
    m2_ok = _close(a.get("m2_gross"), b.get("m2_gross"), tol_abs=3) or (a.get("m2_gross") is None or b.get("m2_gross") is None)
    if not m2_ok:
        return False
    office_a, office_b = fold(a.get("office")), fold(b.get("office"))
    same_office = bool(office_a) and office_a == office_b
    same_floor = a.get("floor_no") is not None and a.get("floor_no") == b.get("floor_no")
    same_m2 = a.get("m2_gross") is not None and a.get("m2_gross") == b.get("m2_gross")
    same_title = fold(a.get("title")) and fold(a.get("title")) == fold(b.get("title"))
    if same_office and (same_m2 or same_floor):
        return True
    if same_title and same_m2:
        return True
    if same_floor and same_m2 and a.get("price") == b.get("price"):
        return True
    # aynı site, aynı ofis numarası (hepsiemlak listingId: <ofis>-<no>)
    if a.get("source") == b.get("source") == "hepsiemlak":
        oa = str(a.get("source_id", "")).split("-")[0]
        ob = str(b.get("source_id", "")).split("-")[0]
        if oa and oa == ob and same_m2:
            return True
    return False


def find_duplicates(listing: dict[str, Any], candidates: Iterable[dict[str, Any]]) -> list[str]:
    return [c["id"] for c in candidates if is_probable_duplicate(listing, c)]
