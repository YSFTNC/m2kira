import pytest

from conftest import load_json
from m2kira.http import ParseError
from m2kira.sources.hepsiemlak import (apply_detail, item_to_listing, list_url, parse_detail_state,
                                       parse_list_state)


def test_list_url():
    assert list_url("cankaya-kizilay") == "https://www.hepsiemlak.com/cankaya-kizilay-kiralik/daire"
    assert list_url("cankaya-kizilay", furnished=True) == "https://www.hepsiemlak.com/cankaya-kizilay-kiralik/daire-esyali"
    assert list_url("cankaya-kizilay", max_price=39000, page=2) == "https://www.hepsiemlak.com/cankaya-kizilay-kiralik/daire?maxPrice=39000&page=2"
    assert list_url("100-yil-isci-bloklari-kiralik/daire", furnished=True) == "https://www.hepsiemlak.com/100-yil-isci-bloklari-kiralik/daire-esyali"


def test_parse_list_kizilay_esyali():
    state = load_json("hepsiemlak_list_kizilay_esyali.nuxt.json")
    items, pages, total = parse_list_state(state)
    assert len(items) == 14 and pages == 1 and total == 14
    by_id = {}
    for it in items:
        l = item_to_listing(it, furnished_src=True)
        by_id[l.source_id] = l
    l = by_id["131733-2621"]
    assert l.id == "hepsiemlak:131733-2621"
    assert l.price == 34900 and l.rooms == "1+1" and l.m2_gross == 95 and l.floor == "5. Kat" and l.floor_no == 5
    assert l.district == "Kızılay" and l.url == "https://www.hepsiemlak.com/ankara-cankaya-kizilay-kiralik/daire/131733-2621"
    assert l.lat and l.lon and l.listed_date == "2026-10-17"
    assert l.office == "JÜPİTER GAYRİMENKUL EMLAK" and l.owner_type == "Emlakçıdan" and l.category == "Daire"
    assert by_id["146714-567"].price == 15000 and by_id["146714-567"].district == "Kocatepe"
    assert by_id["129908-1377"].price == 32000 and by_id["129908-1377"].rooms == "1+1"
    assert by_id["129908-1336"].rooms == "1+0"  # Stüdyo
    assert by_id["154593-12"].district == "Namık Kemal" and by_id["154593-12"].m2_net == 57
    assert l.extras["img"].startswith("https://hecdn01.hemlak.com/mncropresize/400/300/ds01/")


def test_parse_list_bad_state():
    with pytest.raises(ParseError):
        parse_list_state({"data": [{"foo": 1}]})


def test_parse_list_discards_parent_list():
    # sonuç yokken site Çankaya genelinden 24 ilanlık "üst bölge" listesi döndürüyor
    state = load_json("hepsiemlak_list_kizilay_esyali.nuxt.json")
    data = state["data"][0]
    data["totalAdvertisement"] = 0
    data["totalPage"] = 0
    data["isParentListAvailable"] = True
    items, pages, total = parse_list_state(state)
    assert items == [] and pages == 0 and total == 0


def test_parse_detail():
    state = load_json("hepsiemlak_detail_131733-2621.nuxt.json")
    d = parse_detail_state(state)
    assert d["furnished_src"] is True
    assert d["price"] == 34900 and d["rooms"] == "1+1"
    assert d["m2_gross"] == 95 and d["m2_net"] == 90
    assert d["floor"] == "5. Kat" and d["floor_count"] == 5
    assert d["building_age"] == "31" and d["heating"] == "Merkezi"
    assert d["elevator"] is True
    assert abs(d["lat"] - 39.92307) < 0.001 and abs(d["lon"] - 32.85425) < 0.001
    assert d["office"] == "JÜPİTER GAYRİMENKUL EMLAK" and d["district"] == "Kızılay"
    assert "NOT" in d["description"]
    assert d["listed_date"] == "2026-10-17"

    items, _, _ = parse_list_state(load_json("hepsiemlak_list_kizilay_esyali.nuxt.json"))
    l = next(item_to_listing(i) for i in items if i["listingId"] == "131733-2621")
    assert l.detail_fetched is False
    apply_detail(l, d)
    assert l.detail_fetched and l.furnished_src is True and l.heating == "Merkezi" and l.elevator is True
