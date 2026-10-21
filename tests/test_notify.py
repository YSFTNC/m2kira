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


def test_members_get_listing_messages_but_not_technical_notices():
    tg, calls = fake_tg()
    tg.extra_chats = ["222"]
    tg.send("<b>ilan</b>", subject="m2kira: new")
    assert [p["chat_id"] for _, p in calls] == ["1", "222"]
    calls.clear()
    tg.send("parser hata", subject="m2kira uyarı")
    assert [p["chat_id"] for _, p in calls] == ["1"]
    calls.clear()
    tg.send_photo("https://x/a.jpg", "<b>kart</b>", subject="m2kira: new")
    assert [(m, p["chat_id"]) for m, p in calls] == [("sendPhoto", "1"), ("sendPhoto", "222")]
    calls.clear()
    tg.send("yanıt", chat_id="222")
    assert [p["chat_id"] for _, p in calls] == ["222"]


def test_heartbeat_after_quiet_hours(cfg, tmp_path):
    from datetime import datetime, timedelta, timezone

    class Cap(Notifier):
        def __init__(self):
            self.sent = []

        def send(self, text, subject="m2kira"):
            self.sent.append((subject, text))
            return True

    cap = Cap()
    db = DB(tmp_path / "h.sqlite")
    p = Pipeline(cfg, db, cap, sources=[])
    day = datetime(2026, 10, 21, 16, 0)
    assert p.heartbeat_if_quiet(now=day)                                   # hiç mesaj yok: hemen
    assert cap.sent[-1][0] == "m2kira: durum" and "değişiklik yok" in cap.sent[-1][1]
    assert "sahibinden" in cap.sent[-1][1]
    assert not p.heartbeat_if_quiet(now=day)                               # az önce gönderildi
    old = (datetime.now(timezone.utc) - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.set_setting("last_message_at", old)
    assert not p.heartbeat_if_quiet(now=datetime(2026, 10, 21, 2, 0))       # gece sessiz
    assert p.heartbeat_if_quiet(now=day) and len(cap.sent) == 2


def test_sahibinden_links_point_to_site_page(cfg, tmp_path):
    db = DB(tmp_path / "l.sqlite")
    p = Pipeline(cfg, db, MultiNotifier([]), sources=[])
    sb = {"id": "sahibinden:1328722998", "source": "sahibinden", "url": "https://www.sahibinden.com/ilan/x-1328722998/detay"}
    he = {"id": "hepsiemlak:1-2", "source": "hepsiemlak", "url": "https://www.hepsiemlak.com/x"}
    assert p._listing_link(sb).endswith("#ilan=sahibinden%3A1328722998")
    assert p._listing_link(he) == "https://www.hepsiemlak.com/x"



def test_digest_skips_listings_far_from_m2(cfg, tmp_path):
    from m2kira.models import Event

    class Cap(Notifier):
        def __init__(self):
            self.sent = []

        def send(self, text, subject="m2kira"):
            self.sent.append(text)
            return True

    cap = Cap()
    db = DB(tmp_path / "far.sqlite")
    p = Pipeline(cfg, db, cap, sources=[])
    nb = cfg.neighborhood_by_key("kizilay")
    near = Listing(source="hepsiemlak", source_id="n", url="https://x/n", title="Eşyasız 1+1", price=30000, rooms="1+1",
                   lat=39.9231, lon=32.8542, district="Kızılay", neighborhood_key="kizilay")
    far = Listing(source="hepsiemlak", source_id="f", url="https://x/f", title="Eşyasız 1+1", price=30000, rooms="1+1",
                  lat=39.8850, lon=32.8167, district="Cevizlidere", neighborhood_key="kizilay")   # M2'ye ~2,9 km
    for l in (near, far):
        p.enrich(l, nb)
        p.evaluate(l, cfg.budget)
        db.upsert(l)
        db.add_event(Event(listing_id=l.id, kind="new", new_price=30000, created_at="2026-10-22T10:00:00Z"))
    assert "uzak" in db.get("hepsiemlak:f")["flags"]
    p._notify_events(cfg.budget)
    assert len(cap.sent) == 1 and "https://x/n" in cap.sent[0] and "https://x/f" not in cap.sent[0]
