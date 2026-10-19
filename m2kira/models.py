"""Normalize edilmiş ilan modeli."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class Listing:
    source: str
    source_id: str
    url: str
    title: str = ""
    price: Optional[int] = None
    currency: str = "TL"
    price_includes: list[str] = field(default_factory=list)
    rooms: Optional[str] = None
    m2_gross: Optional[int] = None
    m2_net: Optional[int] = None
    floor: Optional[str] = None
    floor_no: Optional[int] = None
    building_age: Optional[str] = None
    heating: Optional[str] = None
    elevator: Optional[bool] = None
    furnished: str = "unknown"          # full | partial | either | none | unknown
    furnished_src: Optional[bool] = None  # kaynağın kendi eşya bayrağı (varsa)
    district: Optional[str] = None      # mahalle (kaynağın yazdığı)
    county: str = "Çankaya"
    street: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    listed_date: Optional[str] = None   # YYYY-MM-DD
    updated_date: Optional[str] = None
    office: Optional[str] = None
    owner_type: Optional[str] = None    # Emlakçıdan / Sahibinden
    category: Optional[str] = None      # Daire / Residence
    description: str = ""
    flags: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)
    # zenginleştirme
    neighborhood_key: Optional[str] = None   # config'teki mahalle adı (istasyon/medyan için)
    scan_key: Optional[str] = None           # hangi tarama birimi bu ilanı izliyor (yayından kalkma için)
    nearest_station: Optional[str] = None
    distance_m: Optional[int] = None
    walk_minutes_est: Optional[int] = None
    distance_verified: bool = False
    detail_fetched: bool = False
    matches: bool = False
    match_tier: Optional[str] = None    # uygun | pazarlikla

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_id}"

    def text_blob(self) -> str:
        return f"{self.title}\n{self.description}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = self.id
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Listing":
        d = dict(d)
        d.pop("id", None)
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Event:
    listing_id: str
    kind: str                     # new | reappeared | price_drop | price_up | removed
    old_price: Optional[int] = None
    new_price: Optional[int] = None
    id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class ScanResult:
    source: str
    neighborhood: str
    listings: list[Listing] = field(default_factory=list)
    pages: int = 0
    complete: bool = True     # tüm sayfalar başarıyla çekildi mi (yayından kalkma tespiti için şart)
    full_pass: bool = True    # birimin tüm listeleri tarandı mı (False: yalnız hızlı eşyalı listesi)
    scan_key: Optional[str] = None   # yoksa mahalle anahtarı kullanılır
    errors: list[str] = field(default_factory=list)
    url: Optional[str] = None
