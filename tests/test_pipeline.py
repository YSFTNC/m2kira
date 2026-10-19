"""Değişiklik tespiti (yeni / fiyat düşüşü / yayından kalkma), kriter, kopya ve bildirim akışı —
sahte kaynakla, ağ erişimi olmadan."""
import copy

import pytest

from m2kira.db import DB
from m2kira.models import Listing, ScanResult
from m2kira.notify.base import Notifier
from m2kira.pipeline import Pipeline
from m2kira.sources.base import Source


class CaptureNotifier(Notifier):
    name = "capture"

    def __init__(self):
        self.messages = []

    def send(self, text, subject="m2kira"):
        self.messages.append((subject, text))
        return True


class FakeSource(Source):
    name = "hepsiemlak"
    supports_detail = False

    def __init__(self, cfg, listings):
        super().__init__(cfg)
        self.listings = listings
        self.complete = True

    def scan_neighborhood(self, nb):
        return ScanResult(source=self.name, neighborhood=nb.name,
                          listings=[copy.deepcopy(l) for l in self.listings if l.neighborhood_key == nb.key],
                          pages=1, complete=self.complete)


def mk(sid, price, title, nb="kizilay", **kw):
    base = dict(source="hepsiemlak", source_id=sid, url=f"https://www.hepsiemlak.com/x/{sid}", title=title,
                price=price, rooms="1+1", m2_gross=60, floor="3. Kat", floor_no=3, district="Kızılay",
                lat=39.9231, lon=32.8542, office="OFİS A", neighborhood_key=nb)
    base.update(kw)
    return Listing(**base)


@pytest.fixture
def env(cfg, tmp_path):
    cfg.raw["notify_removed"] = True
    cfg.raw["compact_threshold"] = 12
    cfg.neighborhoods = [n for n in cfg.neighborhoods if n.key in ("kizilay", "emek", "yasamkent")]
    db = DB(tmp_path / "t.sqlite")
    notifier = CaptureNotifier()
    return cfg, db, notifier


def test_enrich_and_evaluate(env):
    cfg, db, notifier = env
    p = Pipeline(cfg, db, notifier, sources=[])
    nb = cfg.neighborhood_by_key("kizilay")
    l = mk("1-1", 34900, "KIZILAY'DA EŞYALI 1+1 DAİRE")
    p.enrich(l, nb)
    assert l.furnished == "full" and l.nearest_station == "Kızılay" and l.distance_verified and l.distance_m < 400
    p.evaluate(l, 37000)
    assert l.matches and l.match_tier == "uygun"
    # pazarlıkla
    l2 = mk("1-2", 38500, "Eşyalı 2+1", rooms="2+1")
    p.enrich(l2, nb); p.evaluate(l2, 37000)
    assert l2.matches and l2.match_tier == "pazarlikla" and "pazarlikla" in l2.flags
    # bütçe çok üstü
    l3 = mk("1-3", 45000, "Eşyalı 2+1")
    p.enrich(l3, nb); p.evaluate(l3, 37000)
    assert not l3.matches
    # eşya belirsiz -> bildirilmez
    l4 = mk("1-4", 30000, "Merkezi konumda daire")
    p.enrich(l4, nb); p.evaluate(l4, 37000)
    assert l4.furnished == "unknown" and not l4.matches and "esya_belirsiz" in l4.flags
    # koordinatsız -> mahalle istasyonu + 'mesafe doğrulanmadı'
    l5 = mk("1-5", 30000, "Eşyalı daire", lat=None, lon=None)
    p.enrich(l5, nb); p.evaluate(l5, 37000)
    assert l5.matches and not l5.distance_verified and "mesafe_dogrulanmadi" in l5.flags and l5.nearest_station == "Kızılay"
    # Emek'te koordinat Ankaray Emek'e daha yakın + 'metro' geçiyor -> uyarı ; M2'ye 1 km'den uzak -> uzak
    emek = cfg.neighborhood_by_key("emek")
    l6 = mk("1-6", 30000, "Emek'te metroya 2 dk eşyalı", nb="emek", lat=39.9235, lon=32.8150, district="Emek")
    p.enrich(l6, emek); p.evaluate(l6, 37000)
    assert "ankaray_uyari" in l6.flags and l6.nearest_station == "Milli Kütüphane"
    assert ("uzak" in l6.flags and not l6.matches) or ("sinirda" in l6.flags and l6.matches)
    # günlük kiralık -> hariç
    l7 = mk("1-7", 1500, "Günlük Kiralık Lüks Apart eşyalı")
    p.enrich(l7, nb); p.evaluate(l7, 37000)
    assert "gunluk" in l7.flags and not l7.matches
    # geniş mahalle (require_distance): koordinatsız -> bildirilmez; koordinatlı ve yakınsa -> uygun
    ys = cfg.neighborhood_by_key("yasamkent")
    assert ys.require_distance
    l8 = mk("1-8", 30000, "Yaşamkent eşyalı 1+1", nb="yasamkent", lat=None, lon=None, district="Yaşamkent")
    p.enrich(l8, ys); p.evaluate(l8, 37000)
    assert "mesafe_gerekli" in l8.flags and not l8.matches
    l9 = mk("1-9", 30000, "Koru metro yanı eşyalı 1+1", nb="yasamkent", lat=39.8875, lon=32.6870, district="Yaşamkent")
    p.enrich(l9, ys); p.evaluate(l9, 37000)
    assert l9.matches and l9.nearest_station == "Koru"


def test_scan_lifecycle(env):
    cfg, db, notifier = env
    a = mk("10-1", 34900, "KIZILAY'DA EŞYALI 1+1 DAİRE")
    b = mk("10-2", 36000, "Eşyalı 1+1 ferah daire", office="OFİS B", m2_gross=70)
    c = mk("10-3", 50000, "Eşyalı 3+1 lüks", rooms="3+1")      # bütçe dışı -> kaydedilir, bildirilmez
    src = FakeSource(cfg, [a, b, c])
    p = Pipeline(cfg, db, notifier, sources=[src])

    s1 = p.run_scan()
    assert s1["new"] == 3 and s1["notified"] == 2
    assert len(notifier.messages) == 2
    assert all("Yeni ilan" in m[1] for m in notifier.messages)
    assert db.get("hepsiemlak:10-1")["matches"] and db.get("hepsiemlak:10-1")["notified_at"]
    assert not db.get("hepsiemlak:10-3")["matches"]

    # 2. tarama: a fiyat düştü, b kayboldu (1. kaçış, henüz kalkmadı), c aynı
    notifier.messages.clear()
    src.listings = [mk("10-1", 32000, "KIZILAY'DA EŞYALI 1+1 DAİRE"), c]
    s2 = p.run_scan()
    assert s2["price_drop"] == 1 and s2["removed"] == 0
    assert len(notifier.messages) == 1 and "Fiyat düştü" in notifier.messages[0][1] and "34.900" in notifier.messages[0][1]
    assert db.get("hepsiemlak:10-2")["active"] == 1 and db.get("hepsiemlak:10-2")["miss_count"] == 1
    assert [h["price"] for h in db.price_history("hepsiemlak:10-1")] == [34900, 32000]

    # 3. tarama: b yine yok -> yayından kalktı (bildirilmişti -> haber verilir)
    notifier.messages.clear()
    s3 = p.run_scan()
    assert s3["removed"] == 1
    assert db.get("hepsiemlak:10-2")["active"] == 0
    assert len(notifier.messages) == 1 and "Yayından kalktı" in notifier.messages[0][1]

    # 4. tarama: b geri geldi -> yeniden yayında
    notifier.messages.clear()
    src.listings.append(b)
    p.run_scan()
    assert db.get("hepsiemlak:10-2")["active"] == 1
    assert any("Yeniden yayında" in m[1] for m in notifier.messages)

    # eksik tarama (complete=False) kalkma üretmemeli
    notifier.messages.clear()
    src.listings = [c]
    src.complete = False
    s5 = p.run_scan()
    assert s5["removed"] == 0 and db.get("hepsiemlak:10-1")["active"] == 1

    # gizleme + liste
    assert p.hide("he:10-1") == "hepsiemlak:10-1"
    assert all(r["id"] != "hepsiemlak:10-1" for r in p.matching_listings())
    assert p.hide("10-1", False) == "hepsiemlak:10-1"
    assert any(r["id"] == "hepsiemlak:10-1" for r in p.matching_listings())
    txt = p.summary_text()
    assert "Kızılay" in txt and "medyan" in txt.lower()


def test_duplicates_and_compact(env):
    cfg, db, notifier = env
    cfg.raw["compact_threshold"] = 3
    listings = [mk(f"20-{i}", 30000 + i * 100, f"Eşyalı 1+1 daire {i}", office=f"OFİS {i}") for i in range(6)]
    # 20-0 ile aynı daire, başka ilan no (aynı ofis, aynı m², aynı fiyat)
    listings.append(mk("20-99", 30000, "Eşyalı 1+1 kiralık daire", office="OFİS 0"))
    src = FakeSource(cfg, listings)
    p = Pipeline(cfg, db, notifier, sources=[src])
    s = p.run_scan()
    assert s["new"] == 7
    # kompakt: tek mesaj
    assert len(notifier.messages) == 1 and "değişiklik" in notifier.messages[0][1]
    row = db.get("hepsiemlak:20-99")
    assert any(f.startswith("kopya:") for f in row["flags"]) and "hepsiemlak:20-0" in row["dup_of"]


class FakeCombinedSource(FakeSource):
    """sahibinden gibi tek birleşik arama yapan kaynak."""
    name = "sahibinden"
    per_neighborhood = False

    def scan_neighborhood(self, nb):
        return ScanResult(source=self.name, neighborhood=nb.name, scan_key="sahibinden-arama",
                          listings=[copy.deepcopy(l) for l in self.listings], pages=1, complete=self.complete)


def test_combined_source_maps_neighborhoods(env):
    cfg, db, notifier = env
    a = mk("900", 33000, "Kızılay'da eşyalı 1+1", district="Kızılay", lat=None, lon=None, source="sahibinden")
    b = mk("901", 30000, "Emek eşyalı 2+1", district="Emek", lat=None, lon=None, source="sahibinden")
    c = mk("902", 30000, "Yaşamkent eşyalı 1+1", district="Yaşamkent", lat=None, lon=None, source="sahibinden")
    src = FakeCombinedSource(cfg, [a, b, c])
    p = Pipeline(cfg, db, notifier, sources=[src])
    p.run_scan()
    ra, rb, rc = db.get("sahibinden:900"), db.get("sahibinden:901"), db.get("sahibinden:902")
    assert ra["neighborhood_key"] == "kizilay" and ra["nearest_station"] == "Kızılay" and ra["scan_key"] == "sahibinden-arama"
    assert rb["neighborhood_key"] == "emek" and rb["nearest_station"] == "Milli Kütüphane"
    assert ra["matches"] and rb["matches"]
    assert not rc["matches"] and "mesafe_gerekli" in rc["flags"]   # geniş mahalle, koordinatsız
    # birleşik aramada görünmeyen ilan iki tam taramada kalkar
    src.listings = [a, c]
    p.run_scan(); p.run_scan()
    assert db.get("sahibinden:901")["active"] == 0 and db.get("sahibinden:900")["active"] == 1


def test_fast_pass_does_not_mark_removed(env):
    cfg, db, notifier = env
    a = mk("30-1", 34000, "Eşyalı 1+1")
    src = FakeSource(cfg, [a])
    p = Pipeline(cfg, db, notifier, sources=[src])
    p.run_scan()
    src.listings = []
    orig = src.scan_neighborhood

    def fast_only(nb):
        r = orig(nb)
        r.full_pass = False
        return r
    src.scan_neighborhood = fast_only
    p.run_scan(); p.run_scan(); p.run_scan()
    assert db.get("hepsiemlak:30-1")["active"] == 1   # hızlı geçişler kalkma üretmez
    src.scan_neighborhood = orig
    p.run_scan(); p.run_scan()
    assert db.get("hepsiemlak:30-1")["active"] == 0


def test_transient_errors_notify_only_on_streak(env):
    cfg, db, notifier = env

    class Flaky(FakeSource):
        def scan_neighborhood(self, nb):
            raise ConnectionError("DNS çözülemedi")

    p = Pipeline(cfg, db, notifier, sources=[Flaky(cfg, [])])
    p.run_scan()
    assert not any("Tarama hatası" in m[1] for m in notifier.messages)   # tek seferlik hata sessiz
    p.run_scan()
    assert sum("Tarama hatası" in m[1] for m in notifier.messages) == 1  # art arda 2. taramada uyarı


def test_full_pass_scheduler(cfg, tmp_path):
    from m2kira.sources.base import Source
    db = DB(tmp_path / "s.sqlite")
    s = Source(cfg)
    s.name = "hepsiemlak"
    s.scfg = {"full_scan_every_hours": 24, "max_full_per_run": 2}
    s.db = db
    s.begin_run()
    assert s.claim_full_pass("a") and s.claim_full_pass("b") and not s.claim_full_pass("c")  # taramada en çok 2
    s.mark_full_done("a"); s.mark_full_done("b")
    s.begin_run()
    assert not s.claim_full_pass("a") and s.claim_full_pass("c")  # a 24 saat dolmadan tekrar tam geçmez


def test_budget_and_neighborhood_settings(env):
    cfg, db, notifier = env
    p = Pipeline(cfg, db, notifier, sources=[])
    assert p.budget() == cfg.budget
    p.set_budget(40000)
    assert p.budget() == 40000
    n0 = len(p.neighborhoods())
    nb = p.add_neighborhood("Ayrancı", "Kızılay")
    assert nb.station == "Kızılay" and nb.slug_for("emlakjet") == "ayranci-mahallesi" and nb.slug_for("sahibinden") is None
    assert len(p.neighborhoods()) == n0 + 1
    assert p.remove_neighborhood("Ayrancı") and len(p.neighborhoods()) == n0
    assert p.remove_neighborhood("Kızılay") and len(p.neighborhoods()) == n0 - 1
    p.add_neighborhood("Kızılay")
    assert len(p.neighborhoods()) == n0
