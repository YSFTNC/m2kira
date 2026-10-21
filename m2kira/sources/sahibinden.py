"""sahibinden.com

Durum (19 Ekim 2026, kullanıcının oturumuyla doğrulandı):
  * Düz HTTP / TLS taklidi: Cloudflare 403. Headless Chromium: PerimeterX engeli.
    Playwright'ın kendi Chromium'u: "Güvenlik doğrulaması yapılıyor" döngüsü.
  * Kullanıcının gerçek Chrome'u (ayrı profil + uzaktan hata ayıklama portu, `mode: cdp`):
    doğrulama ve giriş sorunsuz; arama sonuçları geliyor.
  * Arama sonuçları üye girişi istiyor. Bu yüzden sahibinden sunucuda (GitHub Actions/VPS)
    taranamaz; PC kapalıyken sahibinden'in kendi "favori arama" bildirimleri (mobil + e-posta)
    kullanılır, istenirse e-postalar `sahibinden_mail` kaynağıyla Telegram'a aktarılır.

Arama: hedef mahallelerin sahibinden kimlikleri (address_quarter) tek bir URL'de birleştirilir:
  /kiralik-daire?address_city=6&address_town=59&address_quarter=3376&...&a103713=true
      &price_max=39000&sorting=date_desc&pagingSize=50[&pagingOffset=50]
  a103713 = "Eşyalı" filtresi (true/false). 26 mahalle sayfası yerine 2-3 sayfa.
  Mahalle kimlikleri /ajax/search/locationFacets uç noktasından alındı (config.yaml'da).

Liste: table#searchResultsTable tr.searchResultsItem[data-id]; td.searchResultsTitleValue a,
  td.searchResultsAttributeValue (m², oda), td.searchResultsPriceValue, td.searchResultsDateValue,
  td.searchResultsLocationValue ("Kızılay Mh."). DİKKAT: sonuç yoksa (data-totalmatches="0") tablo
  "benzer ilanlar" önerileriyle dolu gelir; bunlar atılır.
Detay: .classifiedInfo h3 (fiyat), p.classifiedLocation, dl.classifiedInfoList
  div.classifiedInfoItem dt/dd, #gmap[data-lat][data-lon], #classifiedDescription.
Fikstürler: tests/fixtures/sahibinden_*_real.html (gerçek sayfalardan kırpıldı, hesap bilgisi yok).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Iterable, Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..browser import BrowserFetcher, display_available
from ..http import BlockedError, LoginRequiredError, ParseError
from ..models import Listing, ScanResult
from ..textnorm import fold, normalize_rooms, parse_date_any, parse_floor_no, parse_int, parse_price
from .base import Source

log = logging.getLogger(__name__)
BASE = "https://www.sahibinden.com"
PAGE_SIZE = 50
CITY_ANKARA = 6
TOWN_CANKAYA = 59
FURNISHED_ATTR = "a103713"
_QUARTER_SUFFIX = re.compile(r"\s*(?:Mh\.|Mah\.|Mahallesi)\s*$", re.I)


def search_url(quarters: Iterable[int | str], price_max: Optional[int] = None, furnished: Optional[bool] = True,
               offset: int = 0, page_size: int = PAGE_SIZE, city: int = CITY_ANKARA, town: int = TOWN_CANKAYA) -> str:
    params: list[tuple[str, Any]] = [("address_country", 1), ("address_city", city), ("address_town", town)]
    params += [("address_quarter", int(q)) for q in quarters]
    if furnished is not None:
        params.append((FURNISHED_ATTR, "true" if furnished else "false"))
    if price_max:
        params.append(("price_max", int(price_max)))
    params += [("sorting", "date_desc"), ("pagingSize", page_size)]
    if offset:
        params.append(("pagingOffset", int(offset)))
    return f"{BASE}/kiralik-daire?" + urlencode(params)


def is_login_page(title: str, url: str) -> bool:
    return "giris" in fold(title) or "secure.sahibinden.com/giris" in (url or "")


UNUSUAL_ACCESS_MSG = ("sahibinden 'olağan dışı erişim tespit ettik' uyarısı verdi (çok sık tarama); "
                      "bir sonraki deneme aralık dolunca")


def is_unusual_access_page(title: str, html: str) -> bool:
    """20.10.2026: arama 30 dakikada bir açılınca sahibinden 'Hata Sayfası / Olağan dışı erişim tespit ettik'
    sayfası döndü (otomatik erişim uyarısı). Bu bir hız sınırıdır, oturum düşmesi değil."""
    t = fold(title)
    return "hata sayfasi" in t and "olagan disi erisim" in fold((html or "")[:200000])


def is_blocked_page(title: str, status: int) -> bool:
    t = (title or "").lower()
    return status == 403 or "denied" in t or "access to this page" in t or "doğrulama" in t


def total_matches(html: str) -> Optional[int]:
    m = re.search(r'data-totalmatches="(\d+)"', html)
    return int(m.group(1)) if m else None


def strip_quarter(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return _QUARTER_SUFFIX.sub("", name).strip() or None


# ---------------------------------------------------------------- liste
def parse_list_html(html: str, default_year: Optional[int] = None) -> list[Listing]:
    """Arama sonuç tablosu -> ilanlar. Toplam sonuç 0 ise (tablo yalnızca öneri) boş liste."""
    if total_matches(html) == 0:
        return []
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select("table#searchResultsTable tr.searchResultsItem") or soup.select("tr.searchResultsItem[data-id]")
    out: dict[str, Listing] = {}
    for row in rows:
        sid = row.get("data-id")
        a = (row.select_one("td.searchResultsTitleValue a.classifiedTitle") or row.select_one("a.classifiedTitle")
             or row.select_one("td.searchResultsTitleValue a[href*='/ilan/']"))
        if not a:
            continue
        href = a.get("href") or ""
        if not sid:
            m = re.search(r"-(\d+)/detay", href)
            sid = m.group(1) if m else None
        if not sid or sid in out:
            continue
        title = a.get("title") or a.get_text(" ", strip=True)
        m2 = None
        rooms = None
        for td in row.select("td.searchResultsAttributeValue"):
            v = td.get_text(" ", strip=True)
            if "+" in v or "stüdyo" in v.lower() or "stu" in fold(v):
                rooms = normalize_rooms(v)
            elif parse_int(v) and m2 is None:
                m2 = parse_int(v)
        price_td = row.select_one("td.searchResultsPriceValue")
        price = parse_price(price_td.get_text(" ", strip=True)) if price_td else None
        date_td = row.select_one("td.searchResultsDateValue")
        listed = None
        if date_td:
            parts = [s.get_text(" ", strip=True) for s in date_td.find_all("span")] or [date_td.get_text(" ", strip=True)]
            listed = parse_date_any(" ".join(parts), default_year=default_year)
        loc_td = row.select_one("td.searchResultsLocationValue")
        district = None
        if loc_td:
            loc_lines = [t.strip() for t in loc_td.get_text("\n").split("\n") if t.strip()]
            district = strip_quarter(loc_lines[-1]) if loc_lines else None
        out[str(sid)] = Listing(
            source="sahibinden",
            source_id=str(sid),
            url=href if href.startswith("http") else f"{BASE}{href}",
            title=title.strip(),
            price=price,
            rooms=rooms,
            m2_gross=m2,
            district=district,
            listed_date=listed,
            category="Daire",
            extras={"img": _thumb(row)},
        )
    return list(out.values())


def _thumb(row) -> Optional[str]:
    """Satırdaki küçük resim -> daha büyük sürüm (lthmb_ -> x5_)."""
    for img in row.select("td.searchResultsLargeThumbnail img") or row.select("img"):
        src = img.get("src") or img.get("data-src") or ""
        # yalnız ilan fotoğrafı (/photos/...); "büyük fotoğraf" gibi simgeler (/assets/) değil
        if src.startswith("http") and "shbdn.com/photos/" in src:
            return src.replace("/lthmb_", "/x5_")
    return None


# ---------------------------------------------------------------- detay
def parse_detail_html(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    info: dict[str, str] = {}
    for item in soup.select("dl.classifiedInfoList div.classifiedInfoItem, dl.classifiedInfoList"):
        dts, dds = item.find_all("dt"), item.find_all("dd")
        for k, v in zip(dts, dds):
            info.setdefault(k.get_text(" ", strip=True).rstrip(":"), v.get_text(" ", strip=True))
    for li in soup.select("ul.classifiedInfoList li"):  # eski düzen
        k, v = li.find("strong"), li.find("span")
        if k and v:
            info.setdefault(k.get_text(" ", strip=True).rstrip(":"), v.get_text(" ", strip=True))
    if not info:
        raise ParseError("sahibinden detay: classifiedInfoList bulunamadı")
    out: dict[str, Any] = {"props": info}
    gmap = soup.select_one("#gmap[data-lat][data-lon]")
    if gmap:
        try:
            out["lat"], out["lon"] = float(gmap["data-lat"]), float(gmap["data-lon"])
        except ValueError:
            pass
    desc = soup.select_one("#classifiedDescription")
    out["description"] = desc.get_text(" ", strip=True) if desc else ""
    h1 = soup.find("h1")
    out["title"] = h1.get_text(" ", strip=True) if h1 else None
    price_el = soup.select_one(".classifiedInfo h3")
    out["price"] = parse_price(price_el.get_text(" ", strip=True)) if price_el else None
    loc = soup.select_one("p.classifiedLocation")
    if loc:
        parts = [a.get_text(" ", strip=True) for a in loc.find_all("a")] or [loc.get_text(" ", strip=True)]
        out["district"] = strip_quarter(parts[-1]) if parts else None
    out["m2_gross"] = parse_int(info.get("m² (Brüt)") or info.get("m2 (Brüt)"))
    out["m2_net"] = parse_int(info.get("m² (Net)") or info.get("m2 (Net)"))
    out["rooms"] = normalize_rooms(info.get("Oda Sayısı"))
    out["building_age"] = info.get("Bina Yaşı")
    out["floor"] = info.get("Bulunduğu Kat")
    out["floor_count"] = parse_int(info.get("Kat Sayısı"))
    out["heating"] = info.get("Isıtma")
    esya = fold(info.get("Eşyalı", ""))
    out["furnished_src"] = True if esya in ("evet", "esyali") else (False if esya in ("hayir", "esyasiz") else None)
    asansor = fold(info.get("Asansör", ""))
    out["elevator"] = True if asansor == "var" else (False if asansor == "yok" else None)
    out["aidat"] = parse_price(info.get("Aidat (TL)")) if info.get("Aidat (TL)") else None
    out["deposit"] = parse_price(info.get("Depozito (TL)")) if info.get("Depozito (TL)") else None
    out["owner_type"] = info.get("Kimden")
    out["listed_date"] = parse_date_any(info.get("İlan Tarihi"))
    return out


def apply_detail(listing: Listing, d: dict[str, Any]) -> Listing:
    if d.get("furnished_src") is not None:
        listing.furnished_src = d["furnished_src"]
    if d.get("description"):
        listing.description = d["description"]
    for k in ("heating", "building_age", "owner_type", "listed_date", "district", "title"):
        if d.get(k) and not getattr(listing, k):
            setattr(listing, k, d[k])
    if d.get("floor"):
        listing.floor = d["floor"]
        listing.floor_no = parse_floor_no(d["floor"])
    for k in ("m2_gross", "m2_net", "rooms", "lat", "lon", "elevator", "price"):
        if d.get(k) is not None:
            setattr(listing, k, d[k])
    for k in ("aidat", "deposit", "floor_count"):
        if d.get(k):
            listing.extras[k] = d[k]
    listing.detail_fetched = True
    return listing


# ---------------------------------------------------------------- kaynak
class SahibindenSource(Source):
    """Tek birleşik arama (tüm hedef mahalleler) üzerinden tarar; mahalle mahalle gezmez."""
    name = "sahibinden"
    supports_detail = True
    per_neighborhood = False

    def __init__(self, cfg):
        super().__init__(cfg)
        self.profile_dir = cfg.data_dir / "profiles" / "sahibinden"
        self.mode = str(self.scfg.get("mode", "cdp"))      # cdp | browser
        self.cdp_url = str(self.scfg.get("cdp_url", "http://127.0.0.1:9222"))
        self.browser = BrowserFetcher(
            profile_dir=self.profile_dir,
            cache_dir=cfg.data_dir / "cache" / "sahibinden",
            min_interval=max(float(cfg.get("request_interval_sec", default=5)), float(self.scfg.get("min_interval_sec", 10))),
            headless=bool(self.scfg.get("headless", False)),
            challenge_wait=60.0,
            cooldown=float(self.scfg.get("cooldown_sec", 90)),
            offscreen=bool(self.scfg.get("offscreen", True)),
            cdp_url=self.cdp_url if self.mode == "cdp" else None,
        )
        self.list_ttl = float(cfg.get("cache", "list_ttl_min", default=20)) * 60
        self.detail_ttl = float(cfg.get("cache", "detail_ttl_hours", default=24)) * 3600
        self.headed_fallback = bool(self.scfg.get("headed_fallback", True)) and self.mode != "cdp"
        self.use_price_filter = bool(self.scfg.get("price_filter", True))

    # ------------------------------------------------------------ arama
    def quarters(self) -> list[int]:
        out: list[int] = []
        for nb in self.cfg.enabled_neighborhoods():
            v = nb.sahibinden
            if v is False or v is None:
                continue
            ids = v if isinstance(v, (list, tuple)) else [v]
            for q in ids:
                if str(q).isdigit() and int(q) not in out:
                    out.append(int(q))
        return out

    def build_url(self, offset: int = 0) -> str:
        return search_url(self.quarters(), price_max=self.price_cap if self.use_price_filter else None,
                          furnished=True, offset=offset)

    def manual_urls(self, nb) -> list[str]:
        return [self.build_url()] if self.quarters() else []

    # ------------------------------------------------------------ kullanıcının Chrome'unu başlat (cdp modu)
    def launch_user_chrome(self) -> Optional[str]:
        """Gerçek Google Chrome'u ayrı bir profil ve uzaktan hata ayıklama portuyla açar.
        Kullanıcı bu pencerede doğrulamayı geçip giriş yapar; taramalar bu Chrome'a bağlanır."""
        import os
        import subprocess
        candidates = [
            os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
            "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
        exe = next((c for c in candidates if c and os.path.exists(c)), None)
        if not exe:
            return None
        profile = self.cfg.data_dir / "chrome-profile"
        profile.mkdir(parents=True, exist_ok=True)
        port = self.cdp_url.rsplit(":", 1)[-1].strip("/") or "9222"
        subprocess.Popen([exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                          "--no-first-run", "--no-default-browser-check", "https://secure.sahibinden.com/giris"],
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        return exe

    def _get(self, url: str, ttl: float):
        bp = self.browser.get(url, ttl=ttl)
        if bp.from_cache:
            return bp
        if is_blocked_page(bp.title, bp.status):
            if self.mode == "cdp":
                raise BlockedError("sahibinden bot koruması: Chrome penceresinde sahibinden.com'u açıp doğrulamayı elle geçin")
            if self.headed_fallback and self.browser.headless and display_available():
                log.info("sahibinden headless engellendi, görünür tarayıcıyla yeniden deneniyor")
                self.browser.restart(headless=False)
                bp = self.browser.get(url, ttl=ttl)
                if is_blocked_page(bp.title, bp.status):
                    raise BlockedError("sahibinden bot koruması (PerimeterX) geçilemedi")
            else:
                raise BlockedError("sahibinden bot koruması (PerimeterX) geçilemedi")
        if is_unusual_access_page(bp.title, bp.html):
            raise BlockedError(UNUSUAL_ACCESS_MSG)
        if is_login_page(bp.title, bp.final_url):
            raise LoginRequiredError("sahibinden oturum istiyor: `python main.py sahibinden-chrome` ile açılan Chrome'da giriş yapın")
        return bp

    def scan_neighborhood(self, nb) -> ScanResult:
        result = ScanResult(source=self.name, neighborhood="sahibinden-arama", scan_key="sahibinden-arama")
        if not self.quarters():
            result.complete = False
            result.errors.append("config.yaml'da sahibinden mahalle kimliği yok")
            return result
        merged: dict[str, Listing] = {}
        offset = 0
        page = 1
        total: Optional[int] = None
        limit = int(getattr(self, "page_limit", 0) or self.max_pages)   # hafif tarama: yalnız 1. sayfa (en yeni 50)
        while page <= limit:
            url = self.build_url(offset)
            if result.url is None:
                result.url = url
            bp = self._get(url, self.list_ttl)
            total = total_matches(bp.html) if total is None else total
            rows = parse_list_html(bp.html)
            result.pages += 1
            if not rows:
                if page == 1 and total is None and "searchResults" not in bp.html:
                    debug = self.cfg.data_dir / "sahibinden_debug.html"
                    debug.write_text(bp.html, encoding="utf-8")
                    raise ParseError(f"sahibinden: liste tablosu bulunamadı (başlık: {bp.title!r}; sayfa {debug} olarak kaydedildi)")
                break
            for l in rows:
                l.furnished_src = True   # arama "Eşyalı: Evet" (a103713=true) filtresiyle yapılıyor
                merged.setdefault(l.id, l)
            offset += PAGE_SIZE
            if total is not None and offset >= total:
                break
            if len(rows) < PAGE_SIZE - 5:
                break
            page += 1
        else:
            result.complete = False          # eksik tarama: yayından kalkma tespiti yapılmaz
            if limit >= self.max_pages:
                result.errors.append(f"sayfa sınırı ({self.max_pages}) aşıldı; toplam {total}")
        result.listings = list(merged.values())
        return result

    def fetch_detail(self, listing: Listing) -> Optional[Listing]:
        if not listing.url:
            return None
        bp = self._get(listing.url, self.detail_ttl)
        if bp.status == 404:
            listing.extras["detail_404"] = True
            return listing
        return apply_detail(listing, parse_detail_html(bp.html))

    # ------------------------------------------------------------ bir kerelik giriş (browser modu)
    def interactive_login(self, timeout_s: int = 600) -> bool:
        if self.mode == "cdp":
            self.browser.restart()
        else:
            self.browser.restart(headless=False, offscreen=False)
        page = self.browser.page
        page.goto("https://secure.sahibinden.com/giris", wait_until="domcontentloaded")
        print("Açılan tarayıcıda sahibinden hesabınızla giriş yapın (gerekirse doğrulamayı da geçin).")
        deadline = time.time() + timeout_s
        logged_in = False
        while time.time() < deadline:
            time.sleep(3)
            try:
                title, url, html = page.title(), page.url, page.content()
            except Exception:
                continue
            if is_blocked_page(title, 200) or is_login_page(title, url) or "moment" in (title or "").lower():
                continue
            if "sahibinden.com" in url and re.search(r"(?i)çıkış|cikis|hesab[ıi]m", html):
                logged_in = True
                break
        ok = False
        if logged_in:
            try:
                bp = self.browser.get(self.build_url(), ttl=0)
                rows = parse_list_html(bp.html)
                print(f"Arama sayfası açıldı: {len(rows)} ilan ayrıştırıldı (toplam {total_matches(bp.html)}).")
                ok = True
            except Exception as exc:  # noqa: BLE001
                print("Arama sayfası denemesi başarısız:", exc)
        time.sleep(2)
        self.browser.close()
        return ok

    def close(self) -> None:
        self.browser.close()
