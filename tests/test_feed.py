"""PC -> GitHub hepsiemlak beslemesi."""
import json
from datetime import datetime, timedelta, timezone

from m2kira.db import DB
from m2kira.feed import listing_to_feed
from m2kira.models import Listing
from m2kira.pipeline import Pipeline
from m2kira.sources.hepsiemlak_feed import HepsiemlakFeedSource


class Cap:
    def __init__(self):
        self.messages = []

    def send(self, text, subject="m2kira"):
        self.messages.append(text)
        return True


def L(sid, price, title="Eşyalı 1+1"):
    return Listing(source="hepsiemlak", source_id=sid, url=f"https://www.hepsiemlak.com/x/{sid}", title=title,
                   price=price, rooms="1+1", m2_gross=60, district="Kızılay", lat=39.9231, lon=32.8542,
                   furnished_src=True, office="OFİS")


def write_feed(path, listings, generated=None, complete=True, full_pass=True, nb="kizilay"):
    gen = generated or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"generated": gen, "source": "hepsiemlak", "errors": [], "listings": len(listings),
               "units": [{"nb": nb, "complete": complete, "full_pass": full_pass, "pages": 1, "errors": [],
                          "listings": [listing_to_feed(l) for l in listings]}]}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return gen


def setup(cfg, tmp_path, monkeypatch):
    cfg.neighborhoods = [n for n in cfg.neighborhoods if n.key == "kizilay"]
    feed = tmp_path / "hepsiemlak.json"
    monkeypatch.setenv("M2KIRA_FEED_FILE", str(feed))
    db = DB(tmp_path / "f.sqlite")
    cap = Cap()
    p = Pipeline(cfg, db, cap, sources=[HepsiemlakFeedSource(cfg)])
    return feed, db, cap, p


def test_feed_roundtrip_and_dedup(cfg, tmp_path, monkeypatch):
    feed, db, cap, p = setup(cfg, tmp_path, monkeypatch)
    write_feed(feed, [L("1-1", 34000), L("1-2", 35000)])
    s1 = p.run_scan()
    assert s1["new"] == 2
    row = db.get("hepsiemlak:1-1")
    assert row["matches"] and row["nearest_station"] == "Kızılay" and row["distance_verified"] and row["furnished"] == "full"
    assert len(cap.messages) == 2
    # aynı besleme ikinci kez işlenmez: kalkma sayacı artmaz, bildirim gitmez
    s2 = p.run_scan()
    assert s2["new"] == 0 and db.get("hepsiemlak:1-1")["miss_count"] == 0 and len(cap.messages) == 2
    # yeni besleme: 1-1 fiyat düştü, 1-2 yok (iki tam beslemede görünmezse kalkar)
    write_feed(feed, [L("1-1", 32000)], generated=(datetime.now(timezone.utc) + timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    s3 = p.run_scan()
    assert s3["price_drop"] == 1 and db.get("hepsiemlak:1-2")["active"] == 1
    write_feed(feed, [L("1-1", 32000)], generated=(datetime.now(timezone.utc) + timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    p.run_scan()
    assert db.get("hepsiemlak:1-2")["active"] == 0


def test_stale_or_missing_feed_is_ignored(cfg, tmp_path, monkeypatch):
    feed, db, cap, p = setup(cfg, tmp_path, monkeypatch)
    s = p.run_scan()                       # dosya yok
    assert s["new"] == 0 and not cap.messages
    assert any("besleme dosyası yok" in e for e in s["errors"])
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_feed(feed, [L("2-1", 30000)], generated=old)
    s = p.run_scan()
    assert s["new"] == 0 and db.get("hepsiemlak:2-1") is None
    assert any("PC kapalı" in e for e in s["errors"])
    assert not any("Tarama hatası" in m for m in cap.messages)   # eski besleme uyarı üretmez


def test_partial_feed_does_not_remove(cfg, tmp_path, monkeypatch):
    feed, db, cap, p = setup(cfg, tmp_path, monkeypatch)
    write_feed(feed, [L("3-1", 30000), L("3-2", 31000)])
    p.run_scan()
    for i in range(3):   # yalnız hızlı geçiş (full_pass=False) beslemeleri
        gen = (datetime.now(timezone.utc) + timedelta(seconds=i + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        write_feed(feed, [L("3-1", 30000)], generated=gen, full_pass=False)
        p.run_scan()
    assert db.get("hepsiemlak:3-2")["active"] == 1


def test_sahibinden_feed_maps_neighborhoods(cfg, tmp_path, monkeypatch):
    from m2kira.sources.hepsiemlak_feed import SahibindenFeedSource
    cfg.neighborhoods = [n for n in cfg.neighborhoods if n.key in ("kizilay", "emek", "umit")]
    feed = tmp_path / "sahibinden.json"
    monkeypatch.setenv("M2KIRA_SB_FEED_FILE", str(feed))
    db = DB(tmp_path / "sb.sqlite")
    cap = Cap()
    p = Pipeline(cfg, db, cap, sources=[SahibindenFeedSource(cfg)])

    def SB(sid, price, district, lat=None, lon=None):
        return Listing(source="sahibinden", source_id=sid, url=f"https://www.sahibinden.com/ilan/x-{sid}/detay",
                       title="Eşyalı daire", price=price, rooms="1+1", m2_gross=55, district=district,
                       lat=lat, lon=lon, furnished_src=True, extras={"img": "https://i0.shbdn.com/photos/x5_1.jpg"})

    def write(listings, sec=0, complete=True):
        gen = (datetime.now(timezone.utc) + timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%SZ")
        feed.write_text(json.dumps({"generated": gen, "source": "sahibinden", "errors": [], "listings": len(listings),
                                    "units": [{"nb": "sahibinden-arama", "complete": complete, "full_pass": True, "pages": 1,
                                               "errors": [], "listings": [listing_to_feed(l) for l in listings]}]},
                                   ensure_ascii=False), encoding="utf-8")

    write([SB("100", 30000, "Kızılay", 39.9231, 32.8542), SB("101", 31000, "Emek"), SB("102", 32000, "Ümit")])
    s = p.run_scan()
    assert s["new"] == 3
    a, b, c = db.get("sahibinden:100"), db.get("sahibinden:101"), db.get("sahibinden:102")
    assert a["neighborhood_key"] == "kizilay" and a["distance_verified"] and a["nearest_station"] == "Kızılay"
    assert b["neighborhood_key"] == "emek" and b["nearest_station"] == "Milli Kütüphane" and not b["distance_verified"]
    assert c["nearest_station"] == "Ümitköy" and all(r["scan_key"] == "sahibinden-arama" for r in (a, b, c))
    assert a["extras"]["img"].startswith("https://i0.shbdn.com/")
    # 101 iki tam beslemede görünmezse kalkar
    write([SB("100", 30000, "Kızılay", 39.9231, 32.8542), SB("102", 32000, "Ümit")], sec=5)
    p.run_scan()
    write([SB("100", 30000, "Kızılay", 39.9231, 32.8542), SB("102", 32000, "Ümit")], sec=10)
    p.run_scan()
    assert db.get("sahibinden:101")["active"] == 0 and db.get("sahibinden:100")["active"] == 1


def test_collect_sahibinden_keeps_list_on_detail_wall(cfg, tmp_path, monkeypatch):
    """Detay sayfasında giriş duvarı çıkarsa detay bırakılır ama liste verisi gönderilir; önbellek korunur."""
    import contextlib
    from m2kira import feed as feedmod
    from m2kira.http import LoginRequiredError
    from m2kira.models import ScanResult

    class FakeSB:
        def __init__(self, cfg):
            self.calls = 0
            self.browser = type("B", (), {"cdp_url": None})()

        def scan_neighborhood(self, nb):
            ls = [Listing(source="sahibinden", source_id=str(i), url=f"https://x/{i}", title="Eşyalı", price=30000 + i,
                          rooms="1+1", district="Kızılay", listed_date=f"2026-10-{10 + i:02d}") for i in range(5)]
            return ScanResult(source="sahibinden", neighborhood="sahibinden-arama", listings=ls, pages=1)

        def fetch_detail(self, l):
            self.calls += 1
            if self.calls == 3:
                raise LoginRequiredError("sahibinden oturum istiyor")
            l.lat, l.lon, l.detail_fetched = 39.92, 32.85, True
            return l

        def close(self):
            pass

    monkeypatch.setattr("m2kira.sources.sahibinden.SahibindenSource", FakeSB)
    monkeypatch.setattr("m2kira.chrome.ChromeSession", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(feedmod.time, "sleep", lambda s: None)
    cfg.raw["data_dir"] = str(tmp_path / "d")
    db = DB(tmp_path / "c.sqlite")
    payload = feedmod.collect_sahibinden(cfg, db, max_details=10)
    assert payload["listings"] == 5 and not payload["errors"]            # liste korunur, uyarı yok
    unit = payload["units"][0]
    with_coords = [l for l in unit["listings"] if l.get("lat")]
    assert len(with_coords) == 2                                       # duvara kadar alınan 2 detay
    cache = json.loads((tmp_path / "d" / "feed" / "sahibinden_details.json").read_text(encoding="utf-8"))
    assert sum(1 for v in cache.values() if v.get("lat")) == 2 and sum(1 for v in cache.values() if v.get("attempts")) == 1


def _patch_feed_push(cfg, monkeypatch, units_by_source):
    """main.py feed-push'u ağ/tarayıcı olmadan çalıştırır; çağrı sırasını kaydeder."""
    import main as mainmod
    from m2kira import feed as feedmod
    calls = []

    def payload(src):
        units = units_by_source[src]
        return {"generated": "t", "source": src, "units": units, "errors": [] if units else ["oturum istiyor"],
                "listings": sum(len(u["listings"]) for u in units)}

    monkeypatch.setattr(mainmod, "load_config", lambda path=None: cfg)
    monkeypatch.setattr(mainmod, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(feedmod, "sync_budget_from_web", lambda c, d: None)
    monkeypatch.setattr(feedmod, "notify_feed_problem", lambda c, d, s, p: calls.append(f"check:{s}:{len(p['units'])}"))
    monkeypatch.setattr(feedmod, "collect_sahibinden",
                        lambda c, d, max_details=None: (calls.append("collect:sahibinden"), payload("sahibinden"))[1])
    monkeypatch.setattr(feedmod, "collect_hepsiemlak", lambda c, d: (calls.append("collect:hepsiemlak"), payload("hepsiemlak"))[1])
    monkeypatch.setattr(feedmod, "push", lambda c, p: (calls.append(f"push:{p['source']}"), "ok")[1])
    monkeypatch.setattr(feedmod, "trigger", lambda c, s: (calls.append(f"trigger:{s}"), True)[1])
    return mainmod, calls


def test_feed_push_runs_sahibinden_first_and_triggers_per_source(cfg, monkeypatch):
    unit = [{"unit": "u", "listings": [{}]}]
    mainmod, calls = _patch_feed_push(cfg, monkeypatch, {"sahibinden": unit, "hepsiemlak": unit})
    assert mainmod.main(["feed-push"]) == 0
    # her gönderimden hemen sonra varsayılan kaynaklarla (boş) tetikleme
    assert calls == ["collect:sahibinden", "check:sahibinden:1", "push:sahibinden", "trigger:",
                     "collect:hepsiemlak", "check:hepsiemlak:1", "push:hepsiemlak", "trigger:"]


def test_feed_push_skips_empty_source_but_continues(cfg, monkeypatch):
    unit = [{"unit": "u", "listings": [{}]}]
    mainmod, calls = _patch_feed_push(cfg, monkeypatch, {"sahibinden": [], "hepsiemlak": unit})
    assert mainmod.main(["feed-push"]) == 1          # sahibinden taranamadı -> görev hata koduyla biter
    assert "push:sahibinden" not in calls and calls.count("trigger:") == 1
    assert calls[-2:] == ["push:hepsiemlak", "trigger:"]


def test_notify_feed_problem_streaks(cfg, tmp_path, monkeypatch):
    from m2kira import feed as feedmod
    import m2kira.notify as notifymod
    sent = []

    class N:
        def send(self, text, subject="m2kira"):
            sent.append(text)
            return True

    monkeypatch.setattr(notifymod, "build_notifier", lambda c: N())
    db = DB(tmp_path / "n.sqlite")
    ok = {"units": [{"unit": "u"}], "errors": []}
    wall = {"units": [], "errors": ["sahibinden: doğrulama sayfası (Bir dakika lütfen)"]}
    feedmod.notify_feed_problem(cfg, db, "sahibinden", wall)
    assert sent == []                                   # tek başarısızlık: sessiz
    feedmod.notify_feed_problem(cfg, db, "sahibinden", wall)
    assert len(sent) == 1 and "2 çalıştırmadır" in sent[0] and "sahibinden-chrome" in sent[0]
    feedmod.notify_feed_problem(cfg, db, "sahibinden", wall)
    assert len(sent) == 1                               # günde en fazla bir
    feedmod.notify_feed_problem(cfg, db, "sahibinden", ok)
    assert db.get_setting("feed_fail_streak:sahibinden") == 0
    feedmod.notify_feed_problem(cfg, db, "sahibinden", {"units": [], "errors": ["sahibinden oturum istiyor"]})
    assert len(sent) == 2 and "oturumu düştü" in sent[1]   # oturum: hemen
