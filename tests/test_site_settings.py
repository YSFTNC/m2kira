"""Web sitesinden gelen ayarlar: doğrulama, uygulama, bildirim filtreleri, yeniden değerlendirme."""
from m2kira import site_settings
from m2kira.db import DB
from m2kira.models import Listing, ScanResult
from m2kira.pipeline import Pipeline
from m2kira.sources.base import Source


class Cap:
    def __init__(self):
        self.messages = []

    def send(self, text, subject="m2kira"):
        self.messages.append(text)
        return True


class Fake(Source):
    name = "hepsiemlak"

    def __init__(self, cfg, listings):
        super().__init__(cfg)
        self.listings = listings

    def scan_neighborhood(self, nb):
        import copy
        return ScanResult(source=self.name, neighborhood=nb.name, pages=1,
                          listings=[copy.deepcopy(l) for l in self.listings if l.neighborhood_key == nb.key])


def L(sid, price, nb="kizilay", lat=39.9231, lon=32.8542, rooms="1+1", district="Kızılay"):
    return Listing(source="hepsiemlak", source_id=sid, url=f"https://x/{sid}", title="Eşyalı daire", price=price,
                   rooms=rooms, m2_gross=60, lat=lat, lon=lon, district=district, neighborhood_key=nb, office=f"O{sid}")


def test_clean_rejects_bad_values():
    s = site_settings._clean({"budget": "çok", "budget_tolerance_pct": 400, "rooms_allowed": ["1+1", "x"],
                              "furnished_accept": [], "notify_removed": "evet", "hidden": {"a:1": 1}, "updated": "2026"})
    assert "budget" not in s and "budget_tolerance_pct" not in s and s["rooms_allowed"] == ["1+1"]
    assert "furnished_accept" not in s and "notify_removed" not in s and s["hidden"] == {"a:1": True}


def test_apply_once_and_every_run(cfg, tmp_path):
    db = DB(tmp_path / "s.sqlite")
    raw = {"updated": "2026-10-20T10:00:00Z", "budget": 42000, "rooms_allowed": ["1+1"], "notify_stations": ["Kızılay"],
           "disabled_neighborhoods": ["Emek"], "favorites": ["hepsiemlak:1"], "hidden": {}}
    ch = site_settings.apply(cfg, db, raw)
    assert "bütçe 42000" in ch and db.get_setting("budget") == 42000 and db.get_setting("disabled_neighborhoods") == ["emek"]
    assert cfg.raw["rooms_allowed"] == ["1+1"] and cfg.raw["favorites"] == ["hepsiemlak:1"]
    # Telegram'dan /butce 39000 -> aynı site dosyası tekrar uygulanınca bütçeyi ezmez
    db.set_setting("budget", 39000)
    assert site_settings.apply(cfg, db, raw) == [] and db.get_setting("budget") == 39000
    eff = site_settings.effective(cfg, db)
    assert eff["budget"] == 39000 and eff["notify_stations"] == ["Kızılay"] and eff["updated"] == "2026-10-20T10:00:00Z"


def test_notify_station_filter_and_favorites(cfg, tmp_path):
    cfg.neighborhoods = [n for n in cfg.neighborhoods if n.key in ("kizilay", "umit")]
    db = DB(tmp_path / "n.sqlite")
    cap = Cap()
    cfg.raw["notify_stations"] = ["Kızılay"]
    a = L("1", 30000)                                                     # Kızılay
    b = L("2", 31000, nb="umit", lat=39.9024, lon=32.6954, district="Ümit")  # Çayyolu/Ümitköy
    src = Fake(cfg, [a, b])
    p = Pipeline(cfg, db, cap, sources=[src])
    p.run_scan()
    assert len(cap.messages) == 1 and "Kızılay" in cap.messages[0]
    # favori ilan: istasyon filtresi dışında da fiyat düşüşü bildirilir
    cfg.raw["favorites"] = ["hepsiemlak:2"]
    cap.messages.clear()
    src.listings = [a, L("2", 29000, nb="umit", lat=39.9024, lon=32.6954, district="Ümit")]
    p.run_scan()
    assert len(cap.messages) == 1 and "favori" in cap.messages[0] and "Fiyat düştü" in cap.messages[0]


def test_reevaluate_after_budget_change(cfg, tmp_path):
    cfg.neighborhoods = [n for n in cfg.neighborhoods if n.key == "kizilay"]
    db = DB(tmp_path / "r.sqlite")
    cap = Cap()
    src = Fake(cfg, [L("5", 41000)])
    p = Pipeline(cfg, db, cap, sources=[src])
    p.run_scan()
    assert not db.get("hepsiemlak:5")["matches"] and not cap.messages
    db.set_setting("budget", 42000)          # siteden / Telegram'dan bütçe artışı
    p2 = Pipeline(cfg, db, cap, sources=[])  # kaynaksız çalıştırma ("Ayarları uygula")
    s = p2.run_scan()
    assert s["now_matching"] == 1 and db.get("hepsiemlak:5")["matches"]
    assert len(cap.messages) == 1 and "Artık kriterlere uyuyor" in cap.messages[0]
    p2.run_scan()
    assert len(cap.messages) == 1             # ikinci kez bildirilmez
