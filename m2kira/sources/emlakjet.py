"""emlakjet.com

Düz HTTP ile açılır (bot koruması yok). Sayfa Next.js (App Router):
  * Liste: <script id="listing-realestate-schema" type="application/ld+json"> içinde @graph
    olarak sayfadaki gerçek ilanlar (öneriler hariç) — ad, url, fiyat, tarih, konum, oda, m², kat.
    HTML kartları (<article data-listing-id>) rozet (Eşyalı), eski fiyat ve ofis adı için okunur.
    Sayfalama bilgisi RSC yükünde ("pagination":{"page":0,"totalPages":N}); URL ?sayfa=N.
  * Detay: ld+json (Product + RealEstateListing/additionalProperty: Eşya Durumu, Aidat, Asansör,
    Isıtma...) + RSC yükündeki "initialListing" nesnesi (koordinat, quickInfos: kat, brüt/net, yaş).

robots.txt: *max_fiyat= ve ?oda_sayisi parametreleri yasak -> filtre parametresi kullanılmaz,
yalnızca mahalle sayfaları + ?sayfa=N gezilir.

Liste URL: https://www.emlakjet.com/kiralik-daire/ankara-cankaya-<mahalle>-mahallesi[?sayfa=N]
Detay URL: https://www.emlakjet.com/ilan/<slug>-<id>
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from ..http import Fetcher, ParseError
from ..models import Listing, ScanResult
from ..textnorm import fold, normalize_rooms, parse_date_any, parse_floor_no, parse_int, parse_price, parse_sqm_pair
from .base import Source

log = logging.getLogger(__name__)
BASE = "https://www.emlakjet.com"

_RSC_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', re.S)
_PAGINATION = re.compile(r'"pagination":\{"page":(\d+),"pageSize":(\d+),"totalItems":(\d+),"totalPages":(\d+)\}')
_ID_FROM_URL = re.compile(r"-(\d+)/?$")


def list_url(slug: str, page: int = 1, category: str = "kiralik-daire") -> str:
    slug = slug if slug.startswith("ankara-") else f"ankara-cankaya-{slug}"
    url = f"{BASE}/{category}/{slug}"
    return f"{url}?sayfa={page}" if page > 1 else url


# ---------------------------------------------------------------- RSC yardımcıları
def extract_rsc_payload(html: str) -> str:
    chunks: list[str] = []
    for m in _RSC_CHUNK.finditer(html):
        try:
            chunks.append(json.loads(m.group(1)))
        except Exception:
            continue
    return "".join(chunks)


def extract_balanced_json(text: str, start: int) -> Optional[str]:
    """`start` konumundaki '{' veya '[' ile başlayan dengeli JSON parçasını döndürür."""
    if start < 0 or start >= len(text) or text[start] not in "{[":
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def extract_json_after_key(payload: str, key: str) -> Optional[dict]:
    idx = payload.find(f'"{key}":')
    if idx < 0:
        return None
    start = idx + len(key) + 3
    raw = extract_balanced_json(payload, start)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _ld_json_blocks(soup: BeautifulSoup) -> list[Any]:
    out = []
    for s in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            out.append(json.loads(s.string or s.get_text() or ""))
        except Exception:
            continue
    return out


def _props(entry: dict) -> dict[str, str]:
    props: dict[str, str] = {}
    for p in entry.get("additionalProperty") or []:
        if isinstance(p, dict) and p.get("name") is not None:
            props[str(p["name"])] = str(p.get("value", ""))
    return props


def _id_from_url(url: str) -> Optional[str]:
    m = _ID_FROM_URL.search(url.split("?")[0].split("#")[0])
    return m.group(1) if m else None


# ---------------------------------------------------------------- liste
def parse_list_html(html: str, expect_district: Optional[str] = None) -> tuple[list[Listing], dict[str, int]]:
    soup = BeautifulSoup(html, "lxml")
    listings: dict[str, Listing] = {}
    for block in _ld_json_blocks(soup):
        graph = block.get("@graph") if isinstance(block, dict) else None
        if not graph:
            continue
        for e in graph:
            if not isinstance(e, dict) or e.get("@type") != "RealEstateListing":
                continue
            url = e.get("url") or (e.get("offers") or {}).get("url") or ""
            sid = _id_from_url(url)
            if not sid:
                continue
            props = _props(e)
            konum = props.get("Konum", "")
            district = konum.split(",")[0].replace("Mahallesi", "").strip() or None
            if expect_district and not fold(konum).startswith(fold(expect_district)):
                continue  # öneri/sponsor kartı, başka mahalle
            gross, _ = parse_sqm_pair(props.get("Metrekare"))
            floor = props.get("Kat")
            tag = props.get("İlan Etiketi", "")
            listing = Listing(
                source="emlakjet",
                source_id=sid,
                url=url,
                title=(e.get("name") or "").strip(),
                price=parse_price((e.get("offers") or {}).get("price")),
                rooms=normalize_rooms(props.get("Oda Sayısı")),
                m2_gross=gross,
                floor=floor,
                floor_no=parse_floor_no(floor),
                district=district,
                listed_date=parse_date_any(e.get("datePosted")),
                category="Daire" if "daire" in fold(props.get("İlan Tipi", "daire")) else props.get("İlan Tipi"),
                extras={"tag": tag},
            )
            if fold(tag) == "esyali":
                listing.furnished_src = True
            listings[sid] = listing

    # HTML kartları: rozetler, eski fiyat, ofis, tarih
    for art in soup.select("article[data-listing-id]"):
        sid = str(art.get("data-listing-id"))
        l = listings.get(sid)
        if not l:
            continue
        badges = [fold(s.get_text(" ", strip=True)) for s in art.select("span[class*=badge-pill], a[data-listing-image] span")]
        badges = [b for b in badges if b and len(b) < 40]
        if any(b == "esyali" for b in badges):
            l.furnished_src = True
        l.extras["badges"] = sorted(set(badges))
        prices = [parse_price(s.get_text()) for s in art.find_all("span") if "₺" in s.get_text()]
        prices = [p for p in prices if p]
        if len(prices) >= 2 and prices[1] != prices[0]:
            l.extras["previous_price"] = prices[1]
        agent = art.select_one(".listing-row-agent-names span")
        if agent:
            l.office = agent.get_text(" ", strip=True) or None
        for meta in art.select("p.listing-row-card-meta"):
            txt = meta.get_text(" ", strip=True)
            m = re.search(r"(\d{2}\.\d{2}\.\d{4})", txt)
            if m:
                l.updated_date = parse_date_any(m.group(1))

    payload = extract_rsc_payload(html)
    meta = {"page": 0, "total_pages": 1, "total_items": len(listings)}
    pm = _PAGINATION.search(payload)
    if pm:
        meta = {"page": int(pm.group(1)), "page_size": int(pm.group(2)),
                "total_items": int(pm.group(3)), "total_pages": int(pm.group(4))}
    return list(listings.values()), meta


# ---------------------------------------------------------------- detay
def parse_detail_html(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, Any] = {}
    props: dict[str, str] = {}
    for block in _ld_json_blocks(soup):
        graph = block.get("@graph") if isinstance(block, dict) else None
        if not graph:
            continue
        for e in graph:
            if not isinstance(e, dict):
                continue
            if e.get("@type") == "Product":
                out["title"] = e.get("name")
                out["description"] = e.get("description") or ""
                out["price"] = parse_price((e.get("offers") or {}).get("price"))
            elif e.get("@type") == "RealEstateListing":
                item = e.get("itemOffered") or {}
                props.update(_props(item))
                ident = e.get("identifier") or {}
                out["listing_id"] = str(ident.get("value")) if ident.get("value") else None
                out["updated_date"] = parse_date_any(e.get("dateModified"))
                addr = e.get("address") or {}
                out["district"] = (addr.get("streetAddress") or "").replace("Mahallesi", "").strip() or None
                fs = (item.get("floorSize") or {}).get("value")
                if parse_int(fs):
                    out["m2_gross"] = parse_int(fs)
    payload = extract_rsc_payload(html)
    init = extract_json_after_key(payload, "initialListing") or {}
    if not props and not init:
        raise ParseError("emlakjet detay: ne ld+json ne initialListing bulundu (site değişmiş olabilir)")
    loc = init.get("location") or {}
    coords = loc.get("coordinates") or {}
    if isinstance(coords, dict) and coords.get("lat") and coords.get("lng"):
        out["lat"], out["lon"] = float(coords["lat"]), float(coords["lng"])
    nb = loc.get("neighborhood") or {}
    if nb.get("name"):
        out["district"] = str(nb["name"]).replace("Mahallesi", "").strip()
    quick = {q.get("name"): q.get("value") for q in (init.get("quickInfos") or []) if isinstance(q, dict)}
    for p in init.get("properties") or []:
        if isinstance(p, dict) and p.get("name"):
            props.setdefault(str(p["name"]), str(p.get("value", "")))
    feats = init.get("features") or {}
    out["rooms"] = normalize_rooms(feats.get("rooms") or quick.get("Oda Sayısı") or props.get("Oda Sayısı"))
    if quick.get("Brüt / Net"):
        g, n = parse_sqm_pair(quick["Brüt / Net"])
        if g:
            out["m2_gross"] = g
        if n:
            out["m2_net"] = n
    elif parse_int(feats.get("grossArea")):
        out["m2_gross"] = parse_int(feats.get("grossArea"))
    if quick.get("Bulunduğu Kat"):
        out["floor"] = quick["Bulunduğu Kat"]
    if quick.get("Binanın Kat Sayısı"):
        out["floor_count"] = parse_int(quick["Binanın Kat Sayısı"])
    if quick.get("Binanın Yaşı"):
        out["building_age"] = str(quick["Binanın Yaşı"])
    price = init.get("price") or {}
    if isinstance(price, dict) and parse_price(price.get("amount")):
        out["price"] = parse_price(price.get("amount"))
        if parse_price(price.get("previousPrice")):
            out["previous_price"] = parse_price(price.get("previousPrice"))
    if init.get("createdAt"):
        out["listed_date"] = parse_date_any(init["createdAt"])
    if init.get("updatedAt"):
        out["updated_date"] = parse_date_any(init["updatedAt"])
    if init.get("title") and not out.get("title"):
        out["title"] = init["title"]
    out["heating"] = props.get("Isıtma Tipi")
    esya = fold(props.get("Eşya Durumu", ""))
    out["furnished_src"] = True if esya == "esyali" else (False if esya == "esyasiz" else None)
    asansor = fold(props.get("Asansör", ""))
    out["elevator"] = True if asansor == "var" else (False if asansor == "yok" else None)
    out["aidat"] = parse_price(props.get("Aidat")) if props.get("Aidat") else None
    out["usage"] = props.get("Kullanım Durumu")
    attrs = init.get("attributes") or {}
    transport = []
    if isinstance(attrs, dict):
        for grp in attrs.values():
            if isinstance(grp, dict):
                transport.extend(grp.get("Ulaşım") or [])
    out["transport"] = transport
    out["props"] = props
    return out


def apply_detail(listing: Listing, d: dict[str, Any]) -> Listing:
    if d.get("furnished_src") is not None:
        listing.furnished_src = d["furnished_src"]
    if d.get("description"):
        listing.description = d["description"]
    for k in ("heating", "building_age", "district", "listed_date", "updated_date", "title"):
        if d.get(k) and not getattr(listing, k):
            setattr(listing, k, d[k])
    if d.get("floor"):
        listing.floor = d["floor"]
        listing.floor_no = parse_floor_no(d["floor"])
    for k in ("m2_gross", "m2_net", "rooms", "elevator", "lat", "lon", "price"):
        if d.get(k) is not None:
            setattr(listing, k, d[k])
    for k in ("aidat", "usage", "previous_price", "floor_count", "transport"):
        if d.get(k):
            listing.extras[k] = d[k]
    listing.detail_fetched = True
    return listing


# ---------------------------------------------------------------- kaynak
class EmlakjetSource(Source):
    name = "emlakjet"
    supports_detail = True

    def __init__(self, cfg):
        super().__init__(cfg)
        self.fetcher = Fetcher(cache_dir=cfg.data_dir / "cache" / "emlakjet",
                               min_interval=float(cfg.get("request_interval_sec", default=5)))
        self.list_ttl = float(cfg.get("cache", "list_ttl_min", default=20)) * 60
        self.detail_ttl = float(cfg.get("cache", "detail_ttl_hours", default=24)) * 3600
        self.categories = list(self.scfg.get("categories") or ["kiralik-daire"])
        self.fast_categories = list(self.scfg.get("fast_categories") or self.categories[:1])

    def manual_urls(self, nb) -> list[str]:
        slug = nb.slug_for("emlakjet")
        return [list_url(slug)] if slug else []

    def scan_neighborhood(self, nb) -> ScanResult:
        result = ScanResult(source=self.name, neighborhood=nb.name)
        slug = nb.slug_for("emlakjet")
        if not slug:
            result.complete = False
            result.errors.append("emlakjet slug'ı tanımlı değil")
            return result
        # fast_categories her taramada; diğerleri (residence) yalnız tam geçişte (full_scan_every_hours)
        full = self.claim_full_pass(nb.key)
        result.full_pass = full
        merged: dict[str, Listing] = {}
        for category in self.categories:
            if not full and category not in self.fast_categories:
                continue
            page = 1
            while page <= self.max_pages:
                url = list_url(slug, page=page, category=category)
                if result.url is None:
                    result.url = url
                resp = self.fetcher.get(url, ttl=self.list_ttl, allow_404=True)
                if resp.status == 404:
                    result.errors.append(f"404: {url} (mahalle slug'ı yanlış olabilir)")
                    result.complete = False
                    break
                listings, meta = parse_list_html(resp.text, expect_district=nb.name)
                result.pages += 1
                if not listings and meta.get("total_items", 0) > 0 and page == 1:
                    raise ParseError(f"emlakjet: {meta['total_items']} ilan var görünüyor ama ayrıştırılamadı: {url}")
                for l in listings:
                    l.neighborhood_key = nb.key
                    merged.setdefault(l.id, l)
                if page >= int(meta.get("total_pages", 1)):
                    break
                page += 1
            else:
                result.complete = False
                result.errors.append(f"sayfa sınırı ({self.max_pages}) aşıldı: {slug}")
        result.listings = list(merged.values())
        return result

    def fetch_detail(self, listing: Listing) -> Optional[Listing]:
        if not listing.url:
            return None
        resp = self.fetcher.get(listing.url, ttl=self.detail_ttl, allow_404=True)
        if resp.status == 404:
            listing.extras["detail_404"] = True
            return listing
        return apply_detail(listing, parse_detail_html(resp.text))
