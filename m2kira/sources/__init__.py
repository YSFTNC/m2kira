"""Kaynak kayıt defteri."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .base import Source

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Config


def build_sources(cfg: "Config") -> list[Source]:
    """config.yaml'daki etkin kaynakları oluşturur. M2KIRA_SOURCES=hepsiemlak,emlakjet gibi bir
    ortam değişkeni verilirse yalnızca o kaynaklar (sunucuda sahibinden tarayıcısını kapatmak için)."""
    from .emlakjet import EmlakjetSource
    from .hepsiemlak import HepsiemlakSource
    from .sahibinden import SahibindenSource
    from .sahibinden_mail import SahibindenMailSource

    only = {s.strip() for s in (os.environ.get("M2KIRA_SOURCES") or "").split(",") if s.strip()}
    out: list[Source] = []
    for cls in (HepsiemlakSource, EmlakjetSource, SahibindenSource, SahibindenMailSource):
        if only and cls.name not in only:
            continue
        if not cfg.source_enabled(cls.name):
            continue
        if cls is SahibindenSource and cfg.source_cfg(cls.name).get("mode", "cdp") == "mail":
            continue  # yalnızca e-posta kaynağı istenmiş
        src = cls(cfg)
        if cls is SahibindenMailSource and not src.configured:
            continue  # IMAP bilgisi yoksa sessizce atla
        out.append(src)
    return out
