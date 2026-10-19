"""config.yaml + .env yükleme."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

from .geo import StationIndex
from .textnorm import fold, slugify

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Neighborhood:
    name: str
    station: str
    hepsiemlak: Optional[str] = None
    emlakjet: Optional[str] = None
    sahibinden: Optional[str] = None
    enabled: bool = True
    note: str = ""
    require_distance: bool = False   # geniş mahalleler: koordinatla doğrulanmamış ilan bildirilmez

    @property
    def key(self) -> str:
        return fold(self.name)

    def slug_for(self, source: str) -> Optional[str]:
        v = getattr(self, source, None)
        if v is False:
            return None
        if v:
            return str(v)
        # otomatik türetme (ör. /mahalle ekle ile girilenler); sahibinden sayısal kimlik ister, türetilemez
        base = slugify(self.name)
        return {
            "hepsiemlak": base,
            "emlakjet": f"{base}-mahallesi",
        }.get(source)


@dataclass
class Config:
    raw: dict[str, Any]
    path: Path
    stations: StationIndex
    neighborhoods: list[Neighborhood]
    env: dict[str, str] = field(default_factory=dict)

    # ---- kısa erişimciler
    def get(self, *keys: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    @property
    def budget(self) -> int:
        return int(self.get("budget", default=37000))

    @property
    def budget_tolerance_pct(self) -> float:
        return float(self.get("budget_tolerance_pct", default=5))

    @property
    def scan_interval_hours(self) -> float:
        return float(self.get("scan_interval_hours", default=2))

    @property
    def timezone(self) -> str:
        return str(self.get("timezone", default="Europe/Istanbul"))

    @property
    def data_dir(self) -> Path:
        p = Path(self.get("data_dir", default="data"))
        return p if p.is_absolute() else (self.path.parent / p)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "m2kira.sqlite"

    def source_cfg(self, name: str) -> dict[str, Any]:
        return dict(self.get("sources", name, default={}) or {})

    def source_enabled(self, name: str) -> bool:
        return bool(self.source_cfg(name).get("enabled", False))

    def enabled_neighborhoods(self) -> list[Neighborhood]:
        return [n for n in self.neighborhoods if n.enabled]

    def neighborhood_by_key(self, key: str) -> Optional[Neighborhood]:
        k = fold(key)
        for n in self.neighborhoods:
            if n.key == k or slugify(n.name) == slugify(key):
                return n
        return None

    def secret(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return self.env.get(name) or os.environ.get(name) or default


def load_config(path: Optional[str | Path] = None) -> Config:
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    load_dotenv(ROOT / ".env")
    load_dotenv(cfg_path.parent / ".env")
    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    stations = StationIndex.from_config(raw.get("stations", []))
    nbs: list[Neighborhood] = []
    for item in raw.get("neighborhoods", []):
        if isinstance(item, str):
            nbs.append(Neighborhood(name=item, station=""))
            continue
        nbs.append(Neighborhood(
            name=str(item["name"]),
            station=str(item.get("station", "")),
            hepsiemlak=item.get("hepsiemlak"),
            emlakjet=item.get("emlakjet"),
            sahibinden=item.get("sahibinden"),
            enabled=bool(item.get("enabled", True)),
            note=str(item.get("note", "")),
            require_distance=bool(item.get("require_distance", False)),
        ))
    env = {k: v for k, v in os.environ.items() if k.startswith(("TELEGRAM_", "SMTP_", "EMAIL_", "NTFY_", "SAHIBINDEN_", "M2KIRA_"))}
    cfg = Config(raw=raw, path=cfg_path, stations=stations, neighborhoods=nbs, env=env)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    return cfg
