import pytest

from conftest import load_text
from m2kira.http import ParseError
from m2kira.sources.emlakjet import (apply_detail, extract_balanced_json, list_url, parse_detail_html,
                                     parse_list_html)


def test_list_url():
    assert list_url("bahcelievler-mahallesi") == "https://www.emlakjet.com/kiralik-daire/ankara-cankaya-bahcelievler-mahallesi"
    assert list_url("bahcelievler-mahallesi", page=3) == "https://www.emlakjet.com/kiralik-daire/ankara-cankaya-bahcelievler-mahallesi?sayfa=3"


def test_balanced_json():
    assert extract_balanced_json('x{"a":{"b":"}"},"c":[1,2]}y', 1) == '{"a":{"b":"}"},"c":[1,2]}'


def test_parse_list_bahcelievler():
    html = load_text("emlakjet_list_bahcelievler.html")
    listings, meta = parse_list_html(html, expect_district="Bahçelievler")
    assert meta["total_pages"] == 1 and meta["total_items"] == 30
    assert len(listings) == 30
    by_id = {l.source_id: l for l in listings}
    l = by_id["19920719"]
    assert l.id == "emlakjet:19920719"
    assert l.price == 37000 and l.rooms == "1+0" and l.m2_gross == 39 and l.floor == "2. Kat"
    assert l.district == "Bahçelievler" and l.listed_date == "2026-09-30"
    assert l.url == "https://www.emlakjet.com/ilan/bahcelievlerde-kiralik-10-ful-esyali-2-kat-payolcer-on-cephe-daire-19920719"
    assert l.office == "SEFİR EMLAK"
    assert l.extras["img"].startswith("https://imaj.emlakjet.com/resize/480/0/listing/19920719/")
    assert l.extras.get("previous_price") == 39000
    assert "manzarali" in l.extras.get("badges", [])
    # ilan etiketi EŞYALI olan kart -> kaynak bayrağı
    assert by_id["19883760"].furnished_src is True and by_id["19883760"].rooms == "2+1"
    assert all(l.price for l in listings)


def test_parse_list_filters_recommendations():
    html = load_text("emlakjet_list_cayyolu.html")
    listings, meta = parse_list_html(html, expect_district="Çayyolu")
    assert meta["total_items"] == 1 and len(listings) == 1
    assert listings[0].source_id == "19773960" and listings[0].rooms == "4+1" and listings[0].m2_gross == 290
    # yanlış mahalle beklentisi -> öneriler elenir, gerçek ilan da elenir
    assert parse_list_html(html, expect_district="Bahçelievler")[0] == []


def test_parse_detail_19968826():
    html = load_text("emlakjet_detail_19968826.html")
    d = parse_detail_html(html)
    assert d["listing_id"] == "19968826" and d["price"] == 35000
    assert d["furnished_src"] is True and d["elevator"] is True
    assert d["rooms"] == "1+1" and d["m2_gross"] == 60 and d["m2_net"] == 50
    assert d["floor"] == "4.Kat" and d["floor_count"] == 6 and d["building_age"] == "11-15"
    assert d["heating"] == "Merkezi Doğalgaz" and d["aidat"] == 5200
    assert abs(d["lat"] - 39.90245) < 0.001 and abs(d["lon"] - 32.69537) < 0.001
    assert d["district"] == "Ümit" and d["listed_date"] == "2026-10-12"
    assert "Metro" in d["transport"]
    assert "METROSUNA 5 DAK" in d["description"].upper()

    from m2kira.models import Listing
    l = Listing(source="emlakjet", source_id="19968826", url="x", title="Çayyolu'nda 1+1, Metroya 700m Mesafede ,eşyalı Kiralık Daire")
    apply_detail(l, d)
    assert l.detail_fetched and l.lat and l.furnished_src is True and l.extras["aidat"] == 5200 and l.floor_no == 4


def test_parse_detail_garbage():
    with pytest.raises(ParseError):
        parse_detail_html("<html><body>hi</body></html>")
