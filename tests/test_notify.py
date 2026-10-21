"""Telegram fotoğraflı ilan kartı ve geri dönüşler (ağ yok)."""
from m2kira.db import DB
from m2kira.models import Listing
from m2kira.notify.base import MultiNotifier, Notifier
from m2kira.notify.telegram import TelegramNotifier
from m2kira.pipeline import Pipeline


def fake_tg(fail_photo=False):
    tg = TelegramNotifier("x", chat_id="1")
    calls = []

    def call(method, **params):
        calls.append((method, params))
        if method == "sendPhoto" and fail_photo:
            raise RuntimeError("telegram sendPhoto: Bad Request: failed to get HTTP URL content")
        return {}

    tg.call = call
    return tg, calls


def test_send_photo_ok_and_fallbacks():
    tg, calls = fake_tg()
    assert tg.send_photo("https://i0.shbdn.com/photos/1/x5_a.jpg", "<b>Kart</b>")
    assert [m for m, _ in calls] == ["sendPhoto"] and calls[0][1]["parse_mode"] == "HTML"

    tg, calls = fake_tg(fail_photo=True)          # Telegram fotoğrafı indiremedi -> düz mesaj
    assert tg.send_photo("https://imaj.emlakjet.com/a.jpg", "<b>Kart</b>")
    assert [m for m, _ in calls] == ["sendPhoto", "sendMessage"]

    tg, calls = fake_tg()                          # başlık sınırı aşılıyor -> düz mesaj
    tg.send_photo("https://x/a.jpg", "<b>" + "a" * 1100 + "</b>")
    assert [m for m, _ in calls] == ["sendMessage"]


def test_pipeline_uses_photo_for_new_listing(cfg, tmp_path):
    class Cap(Notifier):
        def __init__(self):
            self.photos, self.texts = [], []

        def send(self, text, subject="m2kira"):
            self.texts.append(text)
            return True

        def send_photo(self, photo_url, caption, subject="m2kira"):
            self.photos.append(photo_url)
            return True

    cap = Cap()
    db = DB(tmp_path / "p.sqlite")
    p = Pipeline(cfg, db, MultiNotifier([cap]), sources=[])
    nb = cfg.neighborhood_by_key("kizilay")
    for sid, img in (("1", "https://i0.shbdn.com/photos/1/x5_a.jpg"), ("2", None)):
        l = Listing(source="sahibinden", source_id=sid, url=f"https://x/{sid}", title="Eşyalı 1+1", price=30000,
                    rooms="1+1", lat=39.9231, lon=32.8542, district="Kızılay", neighborhood_key="kizilay",
                    extras={"img": img} if img else {})
        p.enrich(l, nb)
        p.evaluate(l, cfg.budget)
        db.upsert(l)
        from m2kira.models import Event
        db.add_event(Event(listing_id=l.id, kind="new", new_price=30000, created_at="2026-10-20T00:00:00Z"))
    assert p._notify_events(cfg.budget) == 2
    assert cap.photos == ["https://i0.shbdn.com/photos/1/x5_a.jpg"] and len(cap.texts) == 1


def test_digest_reports_every_change_with_reason(cfg, tmp_path):
    from m2kira.models import Event

    class Cap(Notifier):
        def __init__(self):
            self.sent = []

        def send(self, text, subject="m2kira"):
            self.sent.append((subject, text))
            return True

        def send_photo(self, photo_url, caption, subject="m2kira"):
            self.sent.append((subject, caption))
            return True

    cfg.raw["rooms_allowed"] = ["1+1"]
    cap = Cap()
    db = DB(tmp_path / "d.sqlite")
    p = Pipeline(cfg, db, cap, sources=[])
    nb = cfg.neighborhood_by_key("kizilay")
    rows = [("ok", 30000, "1+1", "Eşyalı 1+1"), ("room", 30000, "2+1", "Eşyalı 2+1"), ("cost", 52000, "1+1", "Eşyalı 1+1 lüks"),
            ("bare", 25000, "1+1", "Eşyasız boş 1+1 daire")]
    for sid, price, rooms, title in rows:
        l = Listing(source="hepsiemlak", source_id=sid, url=f"https://x/{sid}", title=title, price=price, rooms=rooms,
                    lat=39.9231, lon=32.8542, district="Kızılay", neighborhood_key="kizilay")
        p.enrich(l, nb)
        p.evaluate(l, cfg.budget)
        db.upsert(l)
        db.add_event(Event(listing_id=l.id, kind="new", new_price=price, created_at="2026-10-21T10:00:00Z"))
    assert p._notify_events(cfg.budget) == 4
    subjects = [s for s, _ in cap.sent]
    assert subjects == ["m2kira: new", "m2kira: değişiklikler"]          # uygun olan kart, diğerleri tek özet
    digest = cap.sent[1][1]
    assert "Diğer değişiklikler" in digest and "3 yeni" in digest
    assert "2+1 (seçili oda tipi: 1+1)" in digest and "bütçe üstü" in digest and "eşyasız" in digest

    cfg.raw["notify_all_changes"] = False                                # sitedeki seçenek kapalıysa özet yok
    db.add_event(Event(listing_id="hepsiemlak:room", kind="price_drop", old_price=30000, new_price=28000,
                       created_at="2026-10-21T10:30:00Z"))
    assert p._notify_events(cfg.budget) == 0 and len(cap.sent) == 2
