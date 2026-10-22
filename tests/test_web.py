"""Filtre sayfası dışa aktarımı ve Telegram linkleri."""
import json

from m2kira.db import DB
from m2kira.models import Listing
from m2kira.pipeline import Pipeline
from m2kira.web import build_payload, commute_minutes, commute_targets, export_site, m2_line


class Cap:
    def __init__(self):
        self.messages = []

    def send(self, text, subject="m2kira"):
        self.messages.append(text)
        return True


def seed(cfg, db):
    p = Pipeline(cfg, db, Cap(), sources=[])
    nb = cfg.neighborhood_by_key("kizilay")
    for i, (price, title) in enumerate([(30000, "Eşyalı 1+1"), (34000, "Eşyalı 1+1 balkonlu"), (50000, "Eşyalı 3+1")]):
        l = Listing(source="hepsiemlak", source_id=f"9-{i}", url=f"https://x/{i}", title=title, price=price, rooms="1+1",
                    m2_gross=60, lat=39.9231, lon=32.8542, district="Kızılay", neighborhood_key="kizilay")
        p.enrich(l, nb)
        p.evaluate(l, cfg.budget)
        db.upsert(l)
        db.add_price(l.id, price)
    db.add_price("hepsiemlak:9-1", 32000)   # fiyat düştü
    return p


def test_line_and_commute(cfg):
    line = m2_line(cfg)
    assert [s["name"] for s in line][:3] == ["Kızılay", "Necatibey", "Milli Kütüphane"] and line[-1]["name"] == "Koru"
    t = commute_targets(cfg)
    # Kızılay'dan, 4 dk yürüme: MK = 4 + 3 bekleme + 2 durak × 2.2 = 11.4 -> 11
    cm = commute_minutes("Kızılay", 4, True, cfg, line, t)
    assert cm["MK"] == 11
    # ŞH: 4 yürüme + 3 bekleme + 7 durak × 2.2 (Tarım Bakanlığı) + 15 otobüs = 37.4 -> 37
    assert cm["ŞH"] == 37
    # Milli Kütüphane durağında: bekleme/biniş yok, yalnız yürüme
    assert commute_minutes("Milli Kütüphane", 6, True, cfg, line, t)["MK"] == 6
    # konum yoksa varsayılan yürüme (10 dk)
    assert commute_minutes("Milli Kütüphane", None, False, cfg, line, t)["MK"] == 10
    assert commute_minutes(None, 5, True, cfg, line, t) == {}


def test_payload_and_export(cfg, tmp_path):
    db = DB(tmp_path / "w.sqlite")
    seed(cfg, db)
    d = build_payload(cfg, db)
    assert d["budget"] == cfg.budget and len(d["line"]) == 12 and len(d["targets"]) == 2
    items = {i["id"]: i for i in d["items"]}
    assert items["hepsiemlak:9-0"]["ok"] and items["hepsiemlak:9-0"]["st"] == "Kızılay" and items["hepsiemlak:9-0"]["v"]
    assert items["hepsiemlak:9-1"]["pp"] == 34000          # önceki fiyat (düşüş)
    assert items["hepsiemlak:9-1"]["pdt"] and items["hepsiemlak:9-0"]["pdt"] is None   # düşüş zamanı yalnız düşende
    assert not items["hepsiemlak:9-2"]["ok"]                # bütçe dışı ama listede (Tümü görünümü için)
    assert d["stats"]["Kızılay"]["n"] == 2 and d["stats"]["Kızılay"]["min"] == 30000
    assert set(items["hepsiemlak:9-0"]["cm"]) == {"MK", "ŞH"}
    out = tmp_path / "site"
    info = export_site(cfg, db, out)
    assert info["items"] == 3 and (out / "index.html").exists() and (out / ".nojekyll").exists()
    assert (out / "og.png").exists()
    assert json.loads((out / "photos.json").read_text(encoding="utf-8")) == {}     # bu tohum veride galeri yok
    j = json.loads((out / "data.json").read_text(encoding="utf-8"))
    assert j["items"] and "M2 Kiralık" in (out / "index.html").read_text(encoding="utf-8")


def test_links_and_overview(cfg, tmp_path):
    db = DB(tmp_path / "l.sqlite")
    p = seed(cfg, db)
    assert p.web_link() == "https://ysftnc.github.io/m2kira/"
    assert p.web_link(st="Kızılay").startswith("https://ysftnc.github.io/m2kira/#st=K")
    ov = p.station_overview()
    assert "Kızılay" in ov and "<b>2</b> ilan" in ov and "Filtre sayfası" in ov
    p.send_daily_summary()
    assert "Filtre sayfası" in p.notifier.messages[-1]


def test_payload_photos_skip_emlakjet(cfg, tmp_path):
    """emlakjet görselleri başka siteden yüklenemiyor (403); sahibinden/hepsiemlak görselleri kalır."""
    db = DB(tmp_path / "img.sqlite")
    p = Pipeline(cfg, db, Cap(), sources=[])
    nb = cfg.neighborhood_by_key("kizilay")
    for src, img in [("emlakjet", "https://imaj.emlakjet.com/resize/480/0/listing/1/a.jpg"),
                     ("sahibinden", "https://i0.shbdn.com/photos/1/x5_a.jpg"),
                     ("hepsiemlak", "http://insecure.example/a.jpg")]:
        l = Listing(source=src, source_id="1", url=f"https://x/{src}", title="Eşyalı 1+1", price=30000, rooms="1+1",
                    lat=39.9231, lon=32.8542, district="Kızılay", neighborhood_key="kizilay", extras={"img": img})
        p.enrich(l, nb)
        p.evaluate(l, cfg.budget)
        db.upsert(l)
    items = {i["src"]: i for i in build_payload(cfg, db)["items"]}
    assert items["emlakjet"]["img"] is None and items["emlakjet"]["ni"] is None
    assert items["sahibinden"]["img"] == "https://i0.shbdn.com/photos/1/x5_a.jpg"
    assert items["hepsiemlak"]["img"] is None           # yalnız https



def test_areas_resolve_station_centers(cfg):
    from m2kira.web import _areas
    areas = {a["key"]: a for a in _areas(cfg)}
    assert areas["balgat"]["centers"][0]["name"] == "Balgat" and areas["balgat"]["radius_km"] == 2.0
    u = areas["umitkoy-tarim"]
    assert u["walk_min"] == 17 and [c["name"] for c in u["centers"]] == ["Ümitköy", "Tarım Bakanlığı-Danıştay"]
    assert all(c["lat"] and c["lon"] for c in u["centers"])
