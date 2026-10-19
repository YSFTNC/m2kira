"""Metin normalizasyonu: Türkçe karakter katlama, eşya / fiyat kapsamı / risk bayrağı tespiti,
oda-kat-fiyat-tarih ayrıştırma. Tüm fonksiyonlar saf (yan etkisiz) ve testlenebilir."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Iterable, Optional

_TR = str.maketrans({
    "ı": "i", "İ": "i", "I": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
    "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u", "Û": "u",
})
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[\s ]+")


def fold(text: object) -> str:
    """HTML etiketlerini at, Türkçe harfleri ASCII'ye katla, küçük harfe çevir, boşlukları sadeleştir."""
    if text is None:
        return ""
    t = _TAG.sub(" ", str(text))
    t = t.translate(_TR).lower()
    return _WS.sub(" ", t).strip()


def slugify(text: str) -> str:
    t = fold(text)
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t


# ---------------------------------------------------------------- eşya durumu
_EITHER = re.compile(
    r"esyali\s*(?:veya|ya da|yada|/|-|,|ve)\s*esyasiz"
    r"|esyasiz\s*(?:veya|ya da|yada|/|-|,|ve)\s*esyali"
    r"|esyasiz\s*(?:da|de)\s*(?:olur|olabilir|verilebilir|kiralanabilir)"
    r"|esyali\s*(?:da|de)\s*(?:olur|olabilir|verilebilir|kiralanabilir)"
    r"|esya(?:li|siz)\s*olarak\s*da"
)
_FULL = re.compile(r"\b(?:full|ful|fully|komple|tam|tamamen|lux|luks)\s*(?:esyali|mobilyali|mobleli)")
_FURN = re.compile(r"\b(?:esyali|mobilyali|mobleli)\w*")
# "beyaz eşyalı", "kısmi mobilyalı", "yarı eşyalı" -> kısmi
_WHITE = re.compile(r"beyaz\s*esya\w*|(?:kismi|kismen|yari)\s*(?:esyali|mobilyali|mobleli)\w*")
_UNF = re.compile(r"\besyasiz\w*")

FURNISHED_LABELS = {
    "full": "Eşyalı",
    "partial": "Kısmi eşyalı (beyaz eşya)",
    "either": "Eşyalı veya eşyasız",
    "none": "Eşyasız",
    "unknown": "Eşya durumu belirsiz",
}


def detect_furnished(text: str, source_flag: Optional[bool] = None) -> str:
    """full | partial | either | none | unknown.

    Metin (başlık + açıklama) kaynak bayrağından önceliklidir: kaynak 'Eşyalı' dese bile
    metin 'beyaz eşyalı' diyorsa kısmi, 'eşyalı veya eşyasız' diyorsa 'either' döner.
    """
    t = fold(text)
    if _EITHER.search(t):
        return "either"
    if _FULL.search(t):
        return "full"
    rest = _WHITE.sub(" ", t)
    has_furn = bool(_FURN.search(rest))
    has_white = bool(_WHITE.search(t))
    has_unf = bool(_UNF.search(rest))
    if has_furn and has_unf:
        return "either"
    if has_furn:
        return "full"
    if has_white:
        return "partial"
    if has_unf:
        return "none"
    if source_flag is True:
        return "full"
    if source_flag is False:
        return "none"
    return "unknown"


# ---------------------------------------------------------------- fiyata dahil olanlar
def detect_price_includes(text: str) -> list[str]:
    t = fold(text)
    if re.search(r"dahil\s*degil", t):
        t = re.sub(r"[^.]*dahil\s*degil[^.]*", " ", t)
    if re.search(r"her\s*sey\s*dahil|hersey\s*dahil|tum\s*giderler\s*dahil|butun\s*giderler\s*dahil", t):
        return ["hepsi"]
    out: list[str] = []
    # "faturalar dahil", "kiraya tüm faturalar dahil", "faturalar ve aidat dahil"; ama "aidat bedeli; ısınma dahil" değil
    if re.search(r"fatura\w*(?:\s+\w+){0,3}\s+dahil|dahil(?:\s+\w+){0,2}\s+fatura|faturasiz", t):
        out.append("faturalar")
    if re.search(r"aidat\w*(?:\s+\w+){0,2}\s+dahil|dahil(?:\s+\w+){0,2}\s+aidat|aidatsiz|aidat\w*\s*(?:yok|yoktur|alinmaz)", t):
        out.append("aidat")
    if re.search(r"(?:internet|wifi|wi-fi)\w*(?:\s+\w+){0,2}\s+dahil|dahil(?:\s+\w+){0,2}\s+(?:internet|wifi)", t):
        out.append("internet")
    return out


# ---------------------------------------------------------------- risk / bilgi bayrakları
_FLAG_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("acil", re.compile(r"\bacil\b")),
    ("depozitosuz", re.compile(r"depozitosuz|depozito\s*(?:yok|yoktur|istenmez|alinmaz|alinmayacak)")),
    ("kapora", re.compile(r"\bkapora")),
    # "günlük yaşam / günlük ihtiyaç" gibi ifadeler değil, yalnızca kiralama süresi anlamı
    ("kisa_sureli", re.compile(r"kisa\s*sure|kisa\s*donem|haftalik\s*kira|sezonluk|\baylik\s*kiralik|gunluk\s*(?:kira|fiyat|ucret|konaklama)|gunluk\s*-\s*haftalik|gecelik|airbnb")),
    ("gunluk", re.compile(r"gunluk\s*(?:kira|fiyat|ucret|konaklama|olarak)|gunluk\s*-\s*haftalik|gecelik|airbnb|apart\s*otel")),
    ("kisit", re.compile(
        r"(?:kiz|bayan|kadin|erkek|calisan|aile|memur)\w*\s*(?:ogrenci\w*\s*)?(?:ozel|icin|tercih|verilecek|verilir|kiralik)"
        r"|kadinlara|bayanlara|kizlara|erkeklere|ogrencilere|ogrenciye(?!\s*(?:uygun|de\b|da\b))"
        r"|sadece\s*(?:kiz|bayan|kadin|erkek|ogrenci|aile|memur)"
    )),
    ("oda", re.compile(r"oda\s*olarak|tek\s*oda\s*kiralik|\boda\s*kiralik|ortak\s*kullanim|ev\s*arkadasi|paylasimli|flatmate")),
    ("ankaray_uyari", re.compile(r"ankaray|emek\s*metro|bahcelievler\s*metro|besevler\s*metro|\basti\b|a\.s\.t\.i|maltepe\s*metro"
                                 r"|demirtepe\s*(?:metro|istasyon|durag)")),
    ("kot_bodrum", re.compile(r"\bkot\s*-?\s*[1-3]\b|\bkot\s*kat|yari\s*bodrum|yuksek\s*bodrum|bodrum\s*kat|\bbodrum\b")),
]

FLAG_LABELS = {
    "acil": "ACİL",
    "depozitosuz": "depozitosuz",
    "kapora": "kapora",
    "kisa_sureli": "kısa süreli",
    "gunluk": "günlük/gecelik kiralık",
    "kisit": "kısıt (öğrenci/kadın/erkek vb.)",
    "oda": "oda kiralık / paylaşımlı",
    "ankaray_uyari": "metro = Ankaray olabilir",
    "kot_bodrum": "kot/bodrum kat",
    "fiyat_cok_dusuk": "fiyat bölge medyanının %40+ altında",
    "uzak": "istasyona yürüme mesafesi dışında",
    "sinirda": "yürüme sınırında",
    "mesafe_dogrulanmadi": "mesafe doğrulanmadı",
    "mesafe_gerekli": "geniş mahalle, koordinat doğrulanmadan bildirilmez",
    "pazarlikla": "bütçe üstü (pazarlıkla)",
    "kopya": "muhtemel kopya ilan",
    "esya_belirsiz": "eşya durumu belirsiz",
}


def detect_flags(text: str, floor_text: Optional[str] = None) -> list[str]:
    t = fold(text)
    flags: list[str] = []
    for name, pat in _FLAG_PATTERNS:
        if pat.search(t):
            flags.append(name)
    if floor_text:
        f = fold(floor_text)
        if re.search(r"bodrum|\bkot\b|kot\s*\d", f) and "kot_bodrum" not in flags:
            flags.append("kot_bodrum")
    return flags


# ---------------------------------------------------------------- oda / kat / m² / fiyat / tarih
def normalize_rooms(value: object) -> Optional[str]:
    if value is None:
        return None
    t = fold(value)
    if not t:
        return None
    if re.search(r"stud|\b1\s*\+\s*0\b", t):
        return "1+0"
    m = re.search(r"(\d+(?:[.,]5)?)\s*\+\s*(\d+)", t)
    if m:
        return f"{m.group(1).replace(',', '.')}+{m.group(2)}"
    m = re.search(r"(\d+)\s*oda", t)
    if m:
        return f"{m.group(1)}+0"
    return None


def parse_int(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"-?\d[\d.]*", str(value).replace(" ", " "))
    if not m:
        return None
    try:
        return int(m.group(0).replace(".", ""))
    except ValueError:
        return None


def parse_price(value: object) -> Optional[int]:
    """'37.000 ₺', '35,000 TL', 35000, '1.500.000' -> int (TL). Para birimi döviz ise None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    s = str(value)
    if re.search(r"[$€£]|usd|eur|gbp", s, re.I):
        return None
    t = re.sub(r"[^\d.,]", "", s)
    if not t:
        return None
    if re.fullmatch(r"\d{1,3}(,\d{3})+", t):
        t = t.replace(",", "")
    elif "," in t:
        t = t.split(",")[0]
    t = t.replace(".", "")
    if not t.isdigit():
        return None
    v = int(t)
    return v if v > 0 else None


def parse_sqm_pair(value: object) -> tuple[Optional[int], Optional[int]]:
    """'60 m² / 50 m²' veya ['95 m2', ' / 90 m2'] -> (brüt, net)."""
    if value is None:
        return None, None
    if isinstance(value, (list, tuple)):
        value = " ".join(str(v) for v in value)
    nums = [int(n) for n in re.findall(r"(\d{2,4})\s*m", str(value).replace(" ", " "))]
    if not nums:
        nums = [int(n) for n in re.findall(r"\d{2,4}", str(value))]
    if len(nums) >= 2:
        return nums[0], nums[1]
    if len(nums) == 1:
        return nums[0], None
    return None, None


def parse_floor_no(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    t = fold(value)
    if not t:
        return None
    m = re.search(r"(-?\d+)\s*\.?\s*(?:kat|\b)", t)
    if re.search(r"kot\s*-?\s*(\d)", t):
        return -int(re.search(r"kot\s*-?\s*(\d)", t).group(1))
    if "bodrum" in t:
        return -1
    if re.search(r"zemin|giris|bahce|dukkan|villa", t):
        return 0
    if m:
        return int(m.group(1))
    return None


_TR_MONTHS = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6,
    "temmuz": 7, "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
}


def parse_date_any(value: object, default_year: Optional[int] = None) -> Optional[str]:
    """ISO (2026-10-17T17:29:53.390+00:00), '30.09.2026', '12 Ekim 2026', '19 Ekim' -> 'YYYY-MM-DD'."""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    s = str(value).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    t = fold(s)
    m = re.match(r"(\d{1,2})\s+([a-z]+)\s*(\d{4})?", t)
    if m and m.group(2) in _TR_MONTHS:
        year = int(m.group(3)) if m.group(3) else (default_year or date.today().year)
        return f"{year}-{_TR_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    return None


def join_text(parts: Iterable[Optional[str]]) -> str:
    return " \n".join(p for p in parts if p)
