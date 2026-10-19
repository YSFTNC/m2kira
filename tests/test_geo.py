from m2kira.geo import haversine_m, walk_minutes


def test_haversine_and_nearest(cfg):
    # hepsiemlak 131733-2621 koordinatı -> Kızılay istasyonu ~300 m
    st, d = cfg.stations.nearest(39.923073560757665, 32.854246447113, lines=("M2",))
    assert st.name == "Kızılay"
    assert 200 < d < 400
    # emlakjet 19968826 (Ümit Mah.) -> Ümitköy istasyonu, 1 km'den az olmalı ("metroya 700 m")
    st, d = cfg.stations.nearest(39.902453629946784, 32.695370327339155, lines=("M2",))
    assert st.name in ("Ümitköy", "Çayyolu")
    assert d < 1200
    assert walk_minutes(800) == 12 or walk_minutes(800) == 13
    assert haversine_m(39.92, 32.85, 39.92, 32.85) == 0


def test_station_lookup(cfg):
    assert cfg.stations.get("kizilay").name == "Kızılay"
    assert cfg.stations.get("Milli Kütüphane").name == "Milli Kütüphane"
    assert cfg.stations.get("Söğütözü").line == "M2"
    ank, d = cfg.stations.nearest(39.923203, 32.814899, lines=("ANKARAY",))
    assert ank.name == "Emek" and d < 50
