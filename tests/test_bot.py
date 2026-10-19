"""Telegram komut işleyicisi — ağsız, sahte Telegram istemcisiyle."""
import pytest

from m2kira.bot import TelegramBot
from m2kira.db import DB
from m2kira.models import Listing
from m2kira.pipeline import Pipeline


class FakeTG:
    def __init__(self, chat_id=None):
        self.chat_id = chat_id
        self.sent = []

    def send(self, text, subject="m2kira", chat_id=None):
        self.sent.append(text)
        return True


def msg(text, chat=111):
    return {"text": text, "chat": {"id": chat}}


@pytest.fixture
def bot(cfg, tmp_path):
    cfg.neighborhoods = [n for n in cfg.neighborhoods if n.key in ("kizilay", "emek")]
    db = DB(tmp_path / "bot.sqlite")
    p = Pipeline(cfg, db, FakeTG(), sources=[])
    nb = cfg.neighborhood_by_key("kizilay")
    for i, price in enumerate([30000, 34000, 38500, 50000]):
        l = Listing(source="hepsiemlak", source_id=f"7-{i}", url=f"https://x/{i}", title=f"Eşyalı 1+1 daire {i}",
                    price=price, rooms="1+1", m2_gross=55, lat=39.9231, lon=32.8542, district="Kızılay",
                    neighborhood_key="kizilay")
        p.enrich(l, nb)
        p.evaluate(l, cfg.budget)
        db.upsert(l)
    tg = FakeTG()
    return TelegramBot(p, tg), tg, p


def test_registration_and_auth(bot):
    b, tg, p = bot
    b.handle(msg("/start", chat=111))
    assert tg.chat_id == "111" and p.db.get_setting("chat_id") == "111" and "kaydedildi" in tg.sent[-1]
    b.handle(msg("/liste", chat=222))
    assert "sahibine" in tg.sent[-1]


def test_commands(bot):
    b, tg, p = bot
    tg.chat_id = "111"
    b.handle(msg("/liste"))
    assert "2 ilan" in tg.sent[-1] and "30.000" in tg.sent[-1] and "38.500" not in tg.sent[-1]
    b.handle(msg("/liste pazarlik"))
    assert "38.500" in tg.sent[-1]
    b.handle(msg("/liste istasyon Kızılay"))
    assert "ilan" in tg.sent[-1]
    b.handle(msg("/butce 40000"))
    assert p.budget() == 40000
    b.handle(msg("/butce abc"))
    assert "Sayı" in tg.sent[-1]
    b.handle(msg("/ilan he:7-0"))
    assert "30.000" in tg.sent[-1] and "/gizle he:7-0" in tg.sent[-1]
    b.handle(msg("/gizle he:7-0"))
    assert p.db.get("hepsiemlak:7-0")["hidden"] == 1
    b.handle(msg("/goster 7-0"))
    assert p.db.get("hepsiemlak:7-0")["hidden"] == 0
    b.handle(msg("/mahalle ekle Ayrancı Kızılay"))
    assert any(n.key == "ayranci" for n in p.neighborhoods()) and "Eklendi" in tg.sent[-1]
    b.handle(msg("/mahalle sil Ayrancı"))
    assert not any(n.key == "ayranci" for n in p.neighborhoods())
    b.handle(msg("/mahalle"))
    assert "Kızılay" in tg.sent[-1]
    b.handle(msg("/ozet"))
    assert "Özet" in tg.sent[-1]
    b.handle(msg("/durum"))
    assert "Bütçe" in tg.sent[-1]
    b.handle(msg("/tara"))
    assert p.scan_requested.is_set()
    b.handle(msg("/bilinmeyen"))
    assert "/yardim" in tg.sent[-1]
    b.handle(msg("/yardim@m2kira_bot"))
    assert "komutlar" in tg.sent[-1]
