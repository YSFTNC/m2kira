"""GitHub tarafı: PC'nin gönderdiği hepsiemlak beslemesini (data/feed/hepsiemlak.json) kaynak gibi işler.

- İlan kimlikleri ve ayarlar "hepsiemlak" ile aynıdır (aynı ilanlar, aynı veritabanı satırları).
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


class HepsiemlakFeedSource(Source):
    name = "hepsiemlak"
    select_key = "hepsiemlak_feed"
    supports_detail = False

    def __init__(self, cfg):
        super().__init__(cfg)
        self.fcfg = cfg.source_cfg("hepsiemlak_feed")
        self.path = Path(os.environ.get("M2KIRA_FEED_FILE") or (cfg.data_dir / "feed" / "hepsiemlak.json"))
        self.units: dict[str, dict[str, Any]] = {}
        self.status: str = "yüklenmedi"
        self._reported = False

    def begin_run(self) -> None:
        super().begin_run()
        self.units, self._reported = {}, False
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
        if self.db is not None and self.db.get_setting("feed_processed:hepsiemlak") == gen:
            self.status = "bu besleme zaten işlendi"
            return
        self.units = {u["nb"]: u for u in feed.get("units") or []}
        self.status = f"besleme {gen} ({sum(len(u['listings']) for u in self.units.values())} ilan)"
        if self.db is not None:
            self.db.set_setting("feed_processed:hepsiemlak", gen)
        log.info("hepsiemlak %s", self.status)

    def scan_neighborhood(self, nb) -> ScanResult:
        res = ScanResult(source=self.name, neighborhood=nb.name)
        unit: Optional[dict[str, Any]] = self.units.get(nb.key)
        if unit is None:
            res.complete = False
            res.full_pass = False
            if not self._reported:
                res.errors.append(f"hepsiemlak: {self.status}")
                self._reported = True
            return res
        res.listings = [Listing.from_dict(dict(d, source="hepsiemlak")) for d in unit.get("listings") or []]
        res.complete = bool(unit.get("complete"))
        res.full_pass = bool(unit.get("full_pass"))
        res.pages = int(unit.get("pages") or 0)
        res.errors = list(unit.get("errors") or [])
        return res
