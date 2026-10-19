from conftest import load_text
from m2kira.sources.sahibinden_mail import extract_listings


def test_extract_from_html_mail():
    html = load_text("sahibinden_mail_synthetic.html")
    rows = extract_listings(html, "", "Yeni ilanlar")
    by_id = {r.source_id: r for r in rows}
    assert set(by_id) == {"1234567890", "1198700001"}
    a = by_id["1234567890"]
    assert a.id == "sahibinden:1234567890"
    assert a.url == "https://www.sahibinden.com/ilan/emlak-konut-kiralik-kizilayda-esyali-1-1-metroya-yakin-1234567890/detay"
    assert a.title == "Kızılay'da Eşyalı 1+1 Metroya Yakın" and a.price == 33000 and a.rooms == "1+1"
    assert a.extras["via"] == "mail"
    b = by_id["1198700001"]
    assert b.price == 36500 and b.rooms == "2+1" and "Emek" in b.title


def test_extract_from_plain_text():
    text = ("Yeni ilan: Eşyalı 1+0 daire 28.000 TL\n"
            "https://www.sahibinden.com/ilan/emlak-konut-kiralik-studyo-1111222233/detay\n")
    rows = extract_listings("", text, "Favori arama")
    assert len(rows) == 1 and rows[0].source_id == "1111222233" and rows[0].price == 28000 and rows[0].rooms == "1+0"


def test_mail_listing_matches_without_price(cfg, tmp_path):
    from m2kira.db import DB
    from m2kira.config import Neighborhood
    from m2kira.notify.base import ConsoleNotifier
    from m2kira.pipeline import Pipeline
    p = Pipeline(cfg, DB(tmp_path / "m.sqlite"), ConsoleNotifier(), sources=[])
    rows = extract_listings("", "https://www.sahibinden.com/ilan/kiralik-daire-9999888877/detay", "Yeni ilan")
    l = rows[0]
    l.furnished_src = True
    p.enrich(l, Neighborhood(name="e-posta", station=""))
    p.evaluate(l, 37000)
    assert l.price is None and l.matches and l.match_tier == "uygun"
