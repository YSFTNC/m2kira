"""Kaynak arayüzü. Her site için ayrı modül; parser fonksiyonları saf (HTML/JSON -> Listing)."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from ..models import Listing, ScanResult

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Config, Neighborhood
    from ..db import DB


class Source:
    name: str = "base"
    supports_detail: bool = False
    per_neighborhood: bool = True   # False: tek çağrıda tüm ilanlar (birleşik arama, e-posta)
    site_scraper: bool = True       # ilan sitesine doğrudan istek atar (GitHub'da en az aralık kuralı uygulanır)

    def __init__(self, cfg: "Config"):
        self.cfg = cfg
        self.scfg: dict[str, Any] = cfg.source_cfg(self.name)
        self.db: Optional["DB"] = None      # pipeline atar
        self._full_used = 0

    # --- yardımcılar
    @property
    def price_cap(self) -> int:
        """Bütçe + tolerans, 1000'e yuvarlanmış (liste filtresi için). Bütçe DB'de (/butce) değiştirilmiş olabilir."""
        budget = self.cfg.budget
        if self.db is not None:
            budget = int(self.db.get_setting("budget", budget))
        cap = budget * (1 + self.cfg.budget_tolerance_pct / 100.0)
        return int(math.ceil(cap / 1000.0) * 1000)

    @property
    def max_pages(self) -> int:
        return int(self.scfg.get("max_pages", 5))

    def manual_urls(self, nb: "Neighborhood") -> list[str]:
        """Kullanıcıya 'elle kontrol et' derken verilecek arama linkleri."""
        return []

    # --- tam tarama planlama: hızlı liste her taramada, tam liste (filtresiz/residence) seyrek
    def begin_run(self) -> None:
        self._full_used = 0

    def claim_full_pass(self, unit_key: str) -> bool:
        every = float(self.scfg.get("full_scan_every_hours", 0) or 0)
        if every <= 0 or self.db is None:
            return True
        if self._full_used >= int(self.scfg.get("max_full_per_run", 1000)):
            return False
        last = self.db.get_setting(f"last_full:{self.name}:{unit_key}")
        if last:
            try:
                t = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - t).total_seconds() < every * 3600:
                    return False
            except ValueError:
                pass
        self._full_used += 1
        return True

    def mark_full_done(self, unit_key: str) -> None:
        if self.db is not None:
            self.db.set_setting(f"last_full:{self.name}:{unit_key}",
                                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    # --- arayüz
    def scan_neighborhood(self, nb: "Neighborhood") -> ScanResult:  # pragma: no cover - alt sınıflar
        raise NotImplementedError

    def fetch_detail(self, listing: Listing) -> Optional[Listing]:
        """Detay sayfasından zenginleştirir (eşya, koordinat, açıklama...). Desteklenmiyorsa None."""
        return None

    def close(self) -> None:
        pass
