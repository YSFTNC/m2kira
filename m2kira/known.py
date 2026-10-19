"""Handoff'ta verilen bilinen ilanlar (19 Ekim 2026) — parser/tarama doğrulaması için."""
from __future__ import annotations

KNOWN_ACTIVE: dict[str, dict] = {
    # hepsiemlak
    "hepsiemlak:129908-1377": {"price": 32000, "note": "faturalar dahil, kadınlara özel"},
    "hepsiemlak:131733-2621": {"price": 34900, "note": "eşyalı 1+1 teraslı"},
    "hepsiemlak:146714-567": {"price": 15000, "note": "kız öğrenci ⚠️"},
    "hepsiemlak:153654-135": {"price": 36500},
    "hepsiemlak:25987-2269": {"price": 25000, "note": "eşyalı veya eşyasız"},
    "hepsiemlak:4077-2410": {"price": 35500, "note": "her şey dahil eşyalı 1+1"},
    "hepsiemlak:44819-2375": {"price": 35500, "note": "eşyalı 3+1 yarı bodrum"},
    "hepsiemlak:44819-2381": {"price": 30000, "note": "3+1 Türkocağı Cd."},
    "hepsiemlak:5784-2443": {"price": 35000, "note": "2+1"},
    "hepsiemlak:5784-2447": {"price": 35000, "note": "2+1"},
    "hepsiemlak:7655-1320": {"price": 37500, "note": "stüdyo"},
    "hepsiemlak:54420-2409": {"price": 30000, "note": "mobilyalı 1+1"},
    "hepsiemlak:0-47236360": {},
    "hepsiemlak:0-47307387": {},
    "hepsiemlak:14457-526": {"price": 36500, "note": "kopyası universiteler/14457-532"},
    "hepsiemlak:14457-532": {"price": 36500, "note": "kopya"},
    "hepsiemlak:26614-1620": {"price": 37750, "note": "eşyalı 2+1"},
    # emlakjet
    "emlakjet:19968826": {"price": 35000, "note": "Çayyolu/Ümit eşyalı 1+1 metroya 700 m"},
    "emlakjet:19968817": {},
    "emlakjet:19956486": {"note": "Bahçelievler stüdyo, faturalar dahil, kot 1"},
    "emlakjet:19920719": {"price": 37000, "note": "Bahçelievler stüdyo full eşyalı"},
    "emlakjet:19990667": {},
    "emlakjet:19992619": {"price": 30000, "note": "Emek 3+1 Milli Kütüphane yakını"},
    "emlakjet:19712311": {},
    "emlakjet:19970932": {},
    "emlakjet:19655239": {},
}

KNOWN_GONE: list[str] = [
    "hepsiemlak:1124-6418", "hepsiemlak:6792-5182", "hepsiemlak:8292-4421", "hepsiemlak:4077-2408",
]
