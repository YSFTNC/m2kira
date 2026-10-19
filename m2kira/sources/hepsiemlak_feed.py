"""GitHub tarafı: PC'nin gönderdiği beslemeleri (data/feed/<kaynak>.json) kaynak gibi işler.

- hepsiemlak_feed: mahalle başına birimler (hızlı / tam geçiş bilgisiyle).
- sahibinden_feed: tek birim — 22 mahallelik birleşik arama; ilanlar mahalle adına göre eşlenir.
- İlan kimlikleri ve ayarlar asıl kaynakla aynıdır ("hepsiemlak:<no>", "sahibinden:<no>").
- Besleme `max_age_hours`'tan eskiyse (PC kapalı) ya da aynı besleme daha önce işlendiyse hiçbir şey
  yapılmaz: ilan eklenmez, "yayından kalktı" çıkarımı yapılmaz, hata bildirimi gitmez.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..models import Listing, ScanResult
from .base import Source

log = logging.getLogger(__name__)


class FeedSource(Source):
    name = "hepsiemlak"
    select_key = "hepsiemlak_feed"
    supports_detail = False
    env_var = "M2KIRA_FEED_FILE"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.fcfg = cfg.source_cfg(self.select_key)
        self.path = Path(os.environ.get(self.env_var) or (cfg.data_dir / "feed" / f"{self.name}.json"))
        self.units: dict[str, dict[str, Any]] = {}
        self.status: str = "yüklenmedi"
        self.generated: Optional[str] = None
        self._reported = False

    def begin_run(self) -> None:
        super().begin_run()
        self.units, self._reported, self.generated = {}, False, None
        if not self.path.exists():
            self.status = "besleme dosyası yok (PC hiç göndermedi)"
            return
        try:
            feed = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self.status = f"besleme okunamadı: {exc}"
            return
        gen = str(feed.get("generated") or "")
        try:
            age_h = (datetime.now(timezone.utc) - datetime.strptime(gen, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
        except ValueError:
            self.status = "besleme zamanı okunamadı"
            return
        max_age = float(self.fcfg.get("max_age_hours", 3))
        if age_h > max_age:
            self.status = f"besleme {age_h:.1f} sa önce (PC kapalı olabilir)"
            return
        key = f"feed_processed:{self.name}"
        if self.db is not None and self.db.get_setting(key) == gen:
            self.status = "bu besleme zaten işlendi"
            self._reported = True   # hata değil: sessiz geç
            return
        if not feed.get("units"):
            self.status = "besleme boş: " + "; ".join(feed.get("errors") or [])[:200]
            if self.db is not None:
                self.db.set_setting(key, gen)
            return
        self.units = {u["nb"]: u for u in feed.get("units") or []}
        self.generated = gen
        self.status = f"besleme {gen} ({sum(len(u['listings']) for u in self.units.values())} ilan)"
        if self.db is not None:
            self.db.set_setting(key, gen)
        log.info("%s %s", self.name, self.status)

    def _unit_result(self, nb_name: str, unit: Optional[dict[str, Any]], scan_key: Optional[str] = None) -> ScanResult:
        res = ScanResult(source=self.name, neighborhood=nb_name, scan_key=scan_key)
        if unit is None:
            res.complete = False
            res.full_pass = False
            if not self._reported:
                res.errors.append(f"{self.name}: {self.status}")
                self._reported = True
            return res
        res.listings = [Listing.from_dict(dict(d, source=self.name)) for d in unit.get("listings") or []]
        res.complete = bool(unit.get("complete"))
        res.full_pass = bool(unit.get("full_pass"))
        res.pages = int(unit.get("pages") or 0)
        res.errors = list(unit.get("errors") or [])
        return res

    def scan_neighborhood(self, nb) -> ScanResult:
        return self._unit_result(nb.name, self.units.get(nb.key))


class HepsiemlakFeedSource(FeedSource):
    name = "hepsiemlak"
    select_key = "hepsiemlak_feed"
    env_var = "M2KIRA_FEED_FILE"


class SahibindenFeedSource(FeedSource):
    name = "sahibinden"
    select_key = "sahibinden_feed"
    env_var = "M2KIRA_SB_FEED_FILE"
    per_neighborhood = False

    def scan_neighborhood(self, nb) -> ScanResult:
        unit = self.units.get("sahibinden-arama")
        return self._unit_result("sahibinden-arama", unit, scan_key="sahibinden-arama")
