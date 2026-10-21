from urllib.parse import parse_qs, urlparse

from conftest import load_text
from m2kira.sources.sahibinden import (SahibindenSource, apply_detail, is_blocked_page, is_login_page,
                                       parse_detail_html, parse_list_html, search_url, strip_quarter,
                                       total_matches)


def test_search_url():
    u = search_url([3376, 3378], price_max=39000, offset=50)
    q = parse_qs(urlparse(u).query)
    assert u.startswith("https://www.sahibinden.com/kiralik-daire?")
    assert q["address_quarter"] == ["3376", "3378"] and q["address_city"] == ["6"] and q["address_town"] == ["59"]
    assert q["a103713"] == ["true"] and q["price_max"] == ["39000"] and q["pagingOffset"] == ["50"]
    assert q["sorting"] == ["date_desc"] and q["pagingSize"] == ["50"]


def test_parse_real_list():
    html = load_text("sahibinden_list_real.html")
    assert total_matches(html) == 73
    rows = parse_list_html(html, default_year=2026)
    assert len(rows) == 50 and len({r.id for r in rows}) == 50
    assert all(r.price and r.price <= 39000 for r in rows)
    assert all(r.url.startswith("https://www.sahibinden.com/ilan/") and r.url.endswith("/detay") for r in rows)
    assert all(r.listed_date and r.listed_date.startswith("2026-") for r in rows)
    districts = {r.district for r in rows}
    assert "Kızılay" in districts and not any(d and d.endswith(("Mh.", "Mah.")) for d in districts)
    by_id = {r.source_id: r for r in rows}
    gordion = by_id["1260966563"]
    assert gordion.price == 35000 and gordion.rooms == "1+0" and gordion.m2_gross == 43 and gordion.district == "Ümit"
    imgs = [r.extras.get("img") for r in rows if r.extras.get("img")]
    assert len(imgs) >= 40 and all(u.startswith("https://i") and "shbdn.com" in u and "/x5_" in u for u in imgs)


def test_suggestions_page_is_empty():
    # Devlet Mah. için 0 sonuç: tablodaki satırlar yalnızca "benzer ilan" önerisi
    html = load_text("sahibinden_list_suggestions.html")
    assert total_matches(html) == 0
    assert parse_list_html(html) == []


def test_parse_real_detail():
    d = parse_detail_html(load_text("sahibinden_detail_real.html"))
    assert d["price"] == 35000 and d["rooms"] == "1+0" and d["m2_gross"] == 43 and d["m2_net"] == 30
    assert d["furnished_src"] is True and d["elevator"] is True and d["aidat"] == 5200 and d["deposit"] is None
    assert d["floor"] == "4" and d["floor_count"] == 6 and d["heating"] == "Merkezi"
    assert abs(d["lat"] - 39.90251) < 0.001 and abs(d["lon"] - 32.69553) < 0.001
    assert d["district"] == "Ümit" and d["listed_date"] == "2026-10-19" and d["owner_type"] == "Emlak Ofisinden"
    assert "GORD" in d["description"].upper()
    from m2kira.models import Listing
    l = Listing(source="sahibinden", source_id="1260966563", url="x", title="t")
    apply_detail(l, d)
    assert l.detail_fetched and l.lat and l.floor_no == 4 and l.extras["aidat"] == 5200


def test_parse_synthetic_list_legacy():
    rows = parse_list_html(load_text("sahibinden_list_synthetic.html"), default_year=2026)
    assert len(rows) == 2 and rows[0].district == "Kızılay" and rows[1].district == "Meşrutiyet"


def test_page_detection_and_helpers():
    assert is_login_page("sahibinden.com Giriş", "https://secure.sahibinden.com/giris?return=...")
    assert not is_login_page("Çankaya Kiralık Daire", "https://www.sahibinden.com/kiralik-daire/x")
    assert is_blocked_page("Access to this page has been denied", 200)
    assert is_blocked_page("Güvenlik doğrulaması yapılıyor", 200)
    assert is_blocked_page("", 403)
    assert strip_quarter("Kızılay Mh.") == "Kızılay" and strip_quarter("Balgat Mah.") == "Balgat"


def test_source_builds_combined_url(cfg):
    src = SahibindenSource(cfg)
    q = src.quarters()
    assert 3376 in q and 3429 in q and 3792 not in q   # Kızılay, Ümit var; Yaşamkent yok
    assert len(q) == 22
    u = src.build_url()
    assert "a103713=true" in u and "price_max=39000" in u



def test_detail_photos_only_own_listing_big_size():
    from m2kira.models import Listing
    from m2kira.sources.sahibinden import apply_detail, extract_photos
    html = ('<img src="https://i0.shbdn.com/photos/72/29/98/thmb_1328722998mde.jpg">'
            '<img data-source="https://i0.shbdn.com/photos/72/29/98/x5_1328722998mde.jpg">'
            '<img src="https://i0.shbdn.com/photos/72/29/98/x5_1328722998abc.jpg">'
            '<img src="https://i0.shbdn.com/photos/11/22/33/x5_1299999999zzz.jpg">')   # benzer ilan
    photos = extract_photos(html)
    assert photos[0] == "https://i0.shbdn.com/photos/72/29/98/x16_1328722998mde.jpg" and len(photos) == 3
    l = Listing(source="sahibinden", source_id="1328722998", url="https://x", title="t")
    apply_detail(l, {"photos": photos})
    assert l.extras["imgs"] == ["https://i0.shbdn.com/photos/72/29/98/x16_1328722998mde.jpg",
                                "https://i0.shbdn.com/photos/72/29/98/x16_1328722998abc.jpg"]
