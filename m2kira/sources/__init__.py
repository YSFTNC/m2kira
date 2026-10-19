"""Kaynak kayıt defteri."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .base import Source

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Config


def build_sources(cfg: "Config") -> list[Source]:
    """config.yaml'daki etkin kaynakları oluşturur. M2KIRA_SOURCES=hepsiemlak_feed,emlakjet gibi bir
    ortam değişkeni verilirse yalnızca o kaynaklar (seçim anahtarı: select_key ya da name)."""
    from .emlakjet import EmlakjetSource
    from .hepsiemlak import HepsiemlakSource
    from .hepsiemlak_feed import HepsiemlakFeedSource
    from .sahibinden import SahibindenSource
    from .sahibinden_mail import SahibindenMailSource

    only = {s.strip() for s in (os.environ.get("M2KIRA_SOURCES") or "").split(",") if s.strip()}
    out: list[Source] = []
    for cls in (HepsiemlakSource, HepsiemlakFeedSource, EmlakjetSource, SahibindenSource, SahibindenMailSource):
        key = getattr(cls, "select_key", cls.name)
        if only:
            if key not in only:
                continue
        elif cls is HepsiemlakFeedSource:
            continue  # besleme yalnızca açıkça istenince (GitHub Actions)
        if not cfg.source_enabled(key):
            continue
        if cls is SahibindenSource and cfg.source_cfg(cls.name).get("mode", "cdp") == "mail":
            continue  # yalnızca e-posta kaynağı istenmiş
        src = cls(cfg)
        if cls is SahibindenMailSource and not src.configured:
            continue  # IMAP bilgisi yoksa sessizce atla
        out.append(src)
    return out
