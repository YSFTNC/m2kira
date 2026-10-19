from m2kira.textnorm import (detect_flags, detect_furnished, detect_price_includes, fold, normalize_rooms,
                             parse_date_any, parse_floor_no, parse_price, parse_sqm_pair)


def test_fold_turkish():
    assert fold("İŞÇİ Blokları ÇAYYOLU Ümitköy") == "isci bloklari cayyolu umitkoy"
    assert fold("<p>Eşyalı&nbsp;daire</p>") == "esyali&nbsp;daire" or "esyali" in fold("<p>Eşyalı daire</p>")


def test_furnished_detection():
    assert detect_furnished("KIZILAY'DA 45 m² TERASLİ EŞYALI KİRALIK DAİRE") == "full"
    assert detect_furnished("1+1 MOBİLYALI DAİRE") == "full"
    assert detect_furnished("Full eşyalı lüks daire") == "full"
    assert detect_furnished("SARAÇOĞLU MAH 1+1 BEYAZ EŞYALI KİRALIK") == "partial"
    assert detect_furnished("Beyaz eşyalı", source_flag=True) == "partial"
    assert detect_furnished("KOT -1 1+1 MERKEZİ 40m² KISMI MOBİLYALI", source_flag=True) == "partial"
    assert detect_furnished("yarı eşyalı daire") == "partial"
    assert detect_furnished("Eşyalı veya eşyasız kiralık 3+1") == "either"
    assert detect_furnished("Eşyalı / Eşyasız seçenekli") == "either"
    assert detect_furnished("eşyasız da olur") == "either"
    assert detect_furnished("Eşyasız 2+1 daire") == "none"
    assert detect_furnished("Merkezi konumda 2+1") == "unknown"
    assert detect_furnished("Merkezi konumda 2+1", source_flag=True) == "full"
    assert detect_furnished("Merkezi konumda 2+1", source_flag=False) == "none"


def test_price_includes():
    assert detect_price_includes("KİRAYA TÜM FATURALAR DAHİL") == ["faturalar"]
    assert detect_price_includes("Her şey dahil eşyalı 1+1") == ["hepsi"]
    assert "aidat" in detect_price_includes("Aidat dahil, faturalar hariç")
    assert detect_price_includes("AİDAT BEDELİ; ISINMA DAHİL 5.200 TL") == []
    assert detect_price_includes("faturalar dahil değil") == []


def test_flags():
    f = detect_flags("KIZ ÖĞRENCİLERE AKAY CADDESİNDE 1+1 EŞYALI")
    assert "kisit" in f
    assert "kisit" in detect_flags("KADINLARA ÖZEL│KİRAYA TÜM FATURALAR DAHİL")
    assert "oda" in detect_flags("(ODA OLARAK) FATURALAR DAHİL EŞYALI KİRALIK")
    # sahibinden'den gelen yurt / oda ilanları (canlı veriden)
    assert "oda" in detect_flags("ANKARA'NIN MERKEZİ KIZILAY'DA KİRALIK YURT DAİRESİ Loft Dairelerde ÇİFT KİŞİLİK ODALARDA")
    assert "oda" in detect_flags("Balgat'da eşyalı kiralık odalar")
    assert "oda" in detect_flags("Erkek öğrenci yurdunda, üniversite öğrencisine")
    assert "oda" in detect_flags("1+0 ODA ŞEKLİNDE KİRAYA VERİLMEKTE OLUP")
    for ok_text in ("Ev sahibi yurt dışında olduğu için eşyalı kiralık 1+1", "KYK yurduna yakın eşyalı 2+1",
                    "2 odalı kiralık daire", "çift kişilik yatak odası, gardırop", "FULL EŞYALI APART DAİRE"):
        assert "oda" not in detect_flags(ok_text), ok_text
    assert "gunluk" in detect_flags("Merkezi Konumda Günlük Kiralık Lüks Apart")
    assert "acil" in detect_flags("ACİL KİRALIK 2+1")
    assert "depozitosuz" in detect_flags("Depozitosuz eşyalı")
    assert "kapora" in detect_flags("kapora ile tutulur")
    assert "kisa_sureli" in detect_flags("kısa süreli kiralık")
    assert "ankaray_uyari" in detect_flags("Emek metro durağına 2 dk")
    assert "ankaray_uyari" in detect_flags("AŞTİ yakını")
    assert "kot_bodrum" in detect_flags("kot 1 daire")
    assert "kot_bodrum" in detect_flags("ferah daire", floor_text="Yarı Bodrum")
    assert "kisit" not in detect_flags("öğrenciye uygun ferah daire")
    assert "gunluk" not in detect_flags("günlük yaşamın tüm ihtiyaçlarına yakın; günlük ihtiyaç için market")
    assert "kisa_sureli" not in detect_flags("haftalık temizlik hizmeti; günlük yaşam kolaylığı")
    assert detect_flags("Merkezi konumda bakımlı 2+1", floor_text="3. Kat") == []


def test_rooms_floor_price_sqm_dates():
    assert normalize_rooms("1+1") == "1+1"
    assert normalize_rooms("1 + 1") == "1+1"
    assert normalize_rooms("Stüdyo") == "1+0"
    assert normalize_rooms("Stüdyo (1+0)") == "1+0"
    assert normalize_rooms("3.5+1") == "3.5+1"
    assert normalize_rooms(None) is None
    assert parse_floor_no("5. Kat") == 5
    assert parse_floor_no("Yüksek Giriş") == 0
    assert parse_floor_no("Yarı Bodrum") == -1
    assert parse_floor_no("Kot 2") == -2
    assert parse_price("37.000 ₺") == 37000
    assert parse_price("35,000 TL") == 35000
    assert parse_price("1.500.000") == 1500000
    assert parse_price(34900) == 34900
    assert parse_price("1.200 USD") is None
    assert parse_price("5200 TL") == 5200
    assert parse_sqm_pair("60 m² / 50 m²") == (60, 50)
    assert parse_sqm_pair(["95 m2\xa0", " / 90 m2"]) == (95, 90)
    assert parse_sqm_pair("125 m²") == (125, None)
    assert parse_date_any("2026-10-17T17:29:53.390+00:00") == "2026-10-17"
    assert parse_date_any("30.09.2026") == "2026-09-30"
    assert parse_date_any("12 Ekim 2026") == "2026-10-12"
    assert parse_date_any("19 Ekim 2026") == "2026-10-19"
    assert parse_date_any("19 Ekim", default_year=2026) == "2026-10-19"
