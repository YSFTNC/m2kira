"""İstasyon koordinatları, haversine mesafe, en yakın istasyon ve yürüme süresi tahmini."""
from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Iterable, Optional

from .textnorm import fold


@dataclass(frozen=True)
class Station:
    name: str
    lat: float
    lon: float
    line: str = "M2"   # M2 | ANKARAY | M2EXT ...

    @property
    def key(self) -> str:
        return fold(self.name)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * asin(sqrt(a))


def walk_minutes(distance_m: float, speed_m_per_min: float = 80.0) -> int:
    """Kuş uçuşu mesafeye %25 sokak payı ekleyip yürüme dakikasına çevirir."""
    return max(1, int(round(distance_m * 1.25 / speed_m_per_min)))


class StationIndex:
    def __init__(self, stations: Iterable[Station]):
        self.stations: list[Station] = list(stations)
        self._by_key = {s.key: s for s in self.stations}

    def get(self, name: str) -> Optional[Station]:
        if not name:
            return None
        k = fold(name)
        if k in self._by_key:
            return self._by_key[k]
        for s in self.stations:
            if k in s.key or s.key in k:
                return s
        return None

    def nearest(self, lat: float, lon: float, lines: Iterable[str] = ("M2",)) -> tuple[Optional[Station], float]:
        lines = set(lines)
        best, best_d = None, float("inf")
        for s in self.stations:
            if s.line not in lines:
                continue
            d = haversine_m(lat, lon, s.lat, s.lon)
            if d < best_d:
                best, best_d = s, d
        return best, best_d

    @classmethod
    def from_config(cls, cfg_stations: Iterable[dict]) -> "StationIndex":
        out = []
        for s in cfg_stations:
            out.append(Station(name=s["name"], lat=float(s["lat"]), lon=float(s["lon"]), line=str(s.get("line", "M2"))))
        return cls(out)
