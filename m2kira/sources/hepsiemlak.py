"""hepsiemlak.com

Site Cloudflare "managed challenge" arkasında: düz HTTP (requests/curl) 403 alır, headless
Chromium geçer. Sayfa bir Nuxt uygulaması; tüm liste/detay verisi `window.__NUXT__` içinde
JSON olarak gelir (koordinat, m², kat, eşya bayrağı dahil). HTML'i ayrıştırmak yerine bu
durumu okuyoruz: `parse_list_state` / `parse_detail_state` saf fonksiyonlardır ve testlerde
kaydedilmiş JSON ile doğrulanır.

Liste URL'leri:
  https://www.hepsiemlak.com/cankaya-<mahalle>-kiralik/daire            (tümü)
  https://www.hepsiemlak.com/cankaya-<mahalle>-kiralik/daire-esyali     (eşyalı filtresi)
  ...?maxPrice=40000&page=2                                             (robots.txt'e göre serbest)
Detay URL: https://www.hepsiemlak.com/ankara-cankaya-<mahalle>-kiralik/daire/<ofisId>-<no>
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..browser import BrowserFetcher
from ..http import ParseError
from ..models import Listing, ScanResult
from ..textnorm import fold, normalize_rooms, parse_date_any, parse_floor_no, parse_int, parse_price
from .base import Source

log = logging.getLogger(__name__)
BASE = "https://www.hepsiemlak.com"


# ---------------------------------------------------------------- URL
def list_url(slug: str, furnished: bool = False, max_price: Optional[int] = None,
             page: int = 1, category: str = "daire") -> str:
    path = slug if "/" in slug else f"{slug}-kiralik/{category}"
    if furnished:
        path += "-esyali"
    params = []
    if max_price:
        params.append(f"maxPrice={int(max_price)}")
    if page > 1:
        params.append(f"page={page}")
    return f"{BASE}/{path}" + (("?" + "&".join(params)) if params else "")


def _find_data(state: Any, key: str) -> Optional[dict]:
    if not isinstance(state, dict):
        return None
    for entry in state.get("data") or []:
        if isinstance(entry, dict) and key in entry:
            return entry
    return None


# ---------------------------------------------------------------- liste
def parse_list_state(state: Any) -> tuple[list[dict], int, int]:
    """Nuxt durumundan (ilanlar, toplam sayfa, toplam ilan)."""
    data = _find_data(state, "list")
    if data is None:
        raise ParseError("hepsiemlak: Nuxt durumunda 'list' bulunamadı (site değişmiş olabilir)")
    items = data.get("list") or []
    total_page = parse_int(data.get("totalPage")) or 1
    total_ads = parse_int(data.get("totalAdvertisement"))
    if total_ads is None:
        total_ads = len(items)
    # Sonuç yoksa site 'list' içine Çankaya genelinden bir "üst bölge" listesi koyuyor
    # (isParentListAvailable=True, totalAdvertisement=0). Bunlar mahalleye ait değil: at.
    if total_ads == 0 or (data.get("isParentListAvailable") and total_ads == 0):
        return [], 0, 0
    return items, total_page, total_ads


def _first(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return v[0] if v else None
    return v


def item_to_listing(it: dict, furnished_src: Optional[bool] = None) -> Listing:
    sqm = it.get("sqm") or {}
    gross = parse_int(_first(sqm.get("grossSqm")))
    net = parse_int(sqm.get("netSqm"))
    floor = (it.get("floor") or {}).get("name")
    loc = it.get("mapLocation") or {}
    firm = it.get("firm") or {}
    owner = it.get("owner") or {}
    detail_url = it.get("detailUrl") or ""
    age = it.get("age")
    listing = Listing(
        source="hepsiemlak",
        source_id=str(it.get("listingId") or it.get("id")),
        url=f"{BASE}/{detail_url.lstrip('/')}" if detail_url else "",
        title=(it.get("title") or "").strip(),
        price=parse_price(it.get("price")),
        currency=str(it.get("currency") or "TL"),
        rooms=normalize_rooms(_first(it.get("roomAndLivingRoom"))),
        m2_gross=gross or None,
        m2_net=net or None,
        floor=floor,
        floor_no=parse_floor_no(floor),
        building_age=str(age) if age is not None else None,
        district=(it.get("district") or {}).get("name"),
        county=(it.get("county") or {}).get("name") or "Çankaya",
        lat=loc.get("lat"),
        lon=loc.get("lon"),
        listed_date=parse_date_any(it.get("startDate") or it.get("createDate")),
        updated_date=parse_date_any(it.get("listingUpdatedDate") or it.get("updatedDate")),
        office=firm.get("name") or owner.get("name"),
        owner_type=it.get("advertiseOwner"),
        category=(it.get("subCategory") or {}).get("typeName"),
        description=(it.get("detailDescription") or "").strip(),
        furnished_src=furnished_src,
        extras={
            "realty_id": it.get("id"),
            "firm_id": firm.get("id"),
            "seller_type": it.get("sellerType"),
            "listing_type": (it.get("category") or {}).get("typeName"),
            "floor_count": (it.get("floor") or {}).get("count"),
        },
    )
    if listing.currency and listing.currency not in ("TL", "TRY"):
        listing.price = None
    return listing


# ---------------------------------------------------------------- detay
def parse_detail_state(state: Any) -> dict[str, Any]:
    data = _find_data(state, "detailData")
    if data is None:
        raise ParseError("hepsiemlak: Nuxt durumunda 'detailData' bulunamadı")
    d = data["detailData"]
    specs = {s.get("title"): s.get("value") for s in (data.get("specs") or []) if isinstance(s, dict)}
    sqm = d.get("sqm") or {}
    loc = d.get("mapLocation") or {}
    attrs = d.get("attributes") or {}
    attr_names = {fold(a.get("name")) for grp in attrs.values() if isinstance(grp, list)
                  for a in grp if isinstance(a, dict)}
    elevator: Optional[bool] = True if "asansor" in attr_names else None
    if d.get("elevator") is not None:
        elevator = bool(d.get("elevator"))
    floor = (d.get("floor") or {}).get("name")
    age = d.get("age")
    heating = (d.get("heating") or {}).get("name") or specs.get("Isınma Tipi")
    out = {
        "furnished_src": d.get("furnished") if isinstance(d.get("furnished"), bool) else None,
        "description": d.get("description") or "",
        "title": d.get("title"),
        "price": parse_price(d.get("price")),
        "lat": loc.get("lat") if not d.get("isMapHidden") else None,
        "lon": loc.get("lon") if not d.get("isMapHidden") else None,
        "heating": heating,
        "building_age": str(age) if age is not None else (specs.get("Bina Yaşı")),
        "floor": floor or specs.get("Bulunduğu Kat"),
        "floor_count": (d.get("floor") or {}).get("count"),
        "m2_gross": parse_int(_first(sqm.get("grossSqm"))),
        "m2_net": parse_int(sqm.get("netSqm")),
        "rooms": normalize_rooms(_first(d.get("roomAndLivingRoom")) or specs.get("Oda Sayısı")),
        "elevator": elevator,
        "office": (d.get("firm") or {}).get("name"),
        "district": (d.get("district") or {}).get("name"),
        "deposit": parse_int((d.get("deposit") or {}).get("amount")) or None,
        "listed_date": parse_date_any(d.get("startDate") or d.get("createdDate")),
        "updated_date": parse_date_any(d.get("updatedDate")),
        "usage": (d.get("usage") or {}).get("name") or specs.get("Kullanım Durumu"),
        "listing_id": d.get("listingId"),
    }
    return out


def apply_detail(listing: Listing, d: dict[str, Any]) -> Listing:
    if d.get("furnished_src") is not None:
        listing.furnished_src = d["furnished_src"]
    if d.get("description"):
        listing.description = d["description"]
    for k in ("heating", "building_age", "floor", "office", "district", "listed_date", "updated_date"):
        if d.get(k) and not getattr(listing, k):
            setattr(listing, k, d[k])
    if d.get("floor"):
        listing.floor = d["floor"]
        listing.floor_no = parse_floor_no(d["floor"])
    for k in ("m2_gross", "m2_net", "rooms", "elevator", "lat", "lon", "price"):
        if d.get(k) is not None:
            setattr(listing, k, d[k])
    if d.get("deposit"):
        listing.extras["deposit"] = d["deposit"]
    if d.get("usage"):
        listing.extras["usage"] = d["usage"]
    listing.detail_fetched = True
    return listing


# ---------------------------------------------------------------- kaynak
class HepsiemlakSource(Source):
    name = "hepsiemlak"
    supports_detail = True

    def __init__(self, cfg):
        super().__init__(cfg)
        profiles = cfg.data_dir / "profiles" / "hepsiemlak"
        # hepsiemlak Cloudflare hız sınırı uyguluyor (5 sn aralıkla ~25 istekten sonra HTTP 429 görüldü);
        # bu kaynak için aralık daha uzun tutulur.
        self.browser = BrowserFetcher(
            profile_dir=profiles,
            cache_dir=cfg.data_dir / "cache" / "hepsiemlak",
            min_interval=max(float(cfg.get("request_interval_sec", default=5)), float(self.scfg.get("min_interval_sec", 15))),
            headless=bool(self.scfg.get("headless", True)),
            cooldown=float(self.scfg.get("cooldown_sec", 120)),
            block_resources=bool(self.scfg.get("block_resources", True)),
        )
        self.list_ttl = float(cfg.get("cache", "list_ttl_min", default=20)) * 60
        self.detail_ttl = float(cfg.get("cache", "detail_ttl_hours", default=24)) * 3600
        self.prefix = str(self.scfg.get("slug_prefix", "cankaya-"))
        self.categories = list(self.scfg.get("categories") or ["daire"])
        self.fast_categories = list(self.scfg.get("fast_categories") or self.categories[:1])

    def _slug(self, nb) -> Optional[str]:
        slug = nb.slug_for("hepsiemlak")
        if not slug:
            return None
        if "/" in slug or slug.startswith(self.prefix):
            return slug
        return f"{self.prefix}{slug}"

    def manual_urls(self, nb) -> list[str]:
        slug = self._slug(nb)
        return [list_url(slug, furnished=True)] if slug else []

    def _fetch_list_pages(self, slug: str, furnished: bool, max_price: Optional[int], category: str,
                          result: ScanResult) -> list[Listing]:
        out: list[Listing] = []
        page = 1
        while page <= self.max_pages:
            url = list_url(slug, furnished=furnished, max_price=max_price, page=page, category=category)
            if page == 1 and result.url is None:
                result.url = url
            bp = self.browser.get(url, ttl=self.list_ttl, state_expr="window.__NUXT__")
            if bp.status == 404:
                result.errors.append(f"404: {url} (mahalle slug'ı yanlış olabilir)")
                result.complete = False
                return out
            if bp.state is None:
                raise ParseError(f"hepsiemlak: __NUXT__ okunamadı: {url} (başlık: {bp.title!r})")
            items, total_pages, total_ads = parse_list_state(bp.state)
            if not items and total_ads > 0:
                raise ParseError(f"hepsiemlak: {total_ads} ilan var görünüyor ama liste boş: {url}")
            result.pages += 1
            for it in items:
                try:
                    out.append(item_to_listing(it, furnished_src=True if furnished else None))
                except Exception as exc:  # tek ilan bozuksa taramayı düşürme
                    log.warning("hepsiemlak ilan ayrıştırılamadı: %s", exc)
            if page >= total_pages:
                break
            page += 1
        else:
            result.complete = False
            result.errors.append(f"sayfa sınırı ({self.max_pages}) aşıldı: {slug}")
        return out

    def scan_neighborhood(self, nb) -> ScanResult:
        result = ScanResult(source=self.name, neighborhood=nb.name)
        slug = self._slug(nb)
        if not slug:
            result.complete = False
            result.errors.append("hepsiemlak slug'ı tanımlı değil")
            return result
        # Hızlı geçiş (her tarama): yalnızca fast_categories'in eşyalı listesi -> yeni ilan / fiyat düşüşü.
        # Tam geçiş (mahalle başına full_scan_every_hours'ta bir, taramada en çok max_full_per_run mahalle):
        # tüm kategorilerin eşyalı + filtresiz listeleri -> bayraksız "eşyalı" ilanlar ve yayından kalkma.
        full = self.claim_full_pass(nb.key)
        result.full_pass = full
        merged: dict[str, Listing] = {}
        for category in self.categories:
            if not full and category not in self.fast_categories:
                continue
            # 1) eşyalı filtresi (kesin bayrak)
            before = result.complete
            for l in self._fetch_list_pages(slug, True, self.price_cap, category, result):
                l.neighborhood_key = nb.key
                merged[l.id] = l
            furnished_ok = result.complete and before
            # 2) filtresiz liste (bütçe tavanıyla) — başlıkta "eşyalı / eşyalı veya eşyasız" yazan ama
            #    site bayrağı olmayan ilanlar için. Eşyalı listesinde olmayanlar kaynak bayrağı "eşyasız"
            #    sayılır (metin bunu ezebilir); böylece gereksiz detay isteği yapılmaz.
            if full and self.scfg.get("scan_unfiltered", True):
                for l in self._fetch_list_pages(slug, False, self.price_cap, category, result):
                    l.neighborhood_key = nb.key
                    if l.id in merged:
                        continue
                    if furnished_ok:
                        l.furnished_src = False
                    merged[l.id] = l
        result.listings = list(merged.values())
        return result

    def fetch_detail(self, listing: Listing) -> Optional[Listing]:
        if not listing.url:
            return None
        bp = self.browser.get(listing.url, ttl=self.detail_ttl, state_expr="window.__NUXT__")
        if bp.status == 404:
            listing.extras["detail_404"] = True
            return listing
        if bp.state is None:
            raise ParseError(f"hepsiemlak detay __NUXT__ okunamadı: {listing.url}")
        if _find_data(bp.state, "detailData") is None:
            # yayından kalkmış ilanlar 200 döner ama detailData içermez (liste/yönlendirme sayfası)
            listing.extras["detail_404"] = True
            listing.detail_fetched = True
            return listing
        return apply_detail(listing, parse_detail_state(bp.state))

    def close(self) -> None:
        self.browser.close()
