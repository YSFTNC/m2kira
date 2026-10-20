"""Tarama orkestrasyonu: kaynak × mahalle çek -> normalize/zenginleştir -> kriter değerlendir
-> SQLite'a yaz + değişiklik (yeni / fiyat düşüşü / yayından kalkma) -> kopya tespiti -> bildirim."""
from __future__ import annotations

import logging
import os
import statistics
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from .config import Config, Neighborhood
from .db import DB, row_to_listing, utcnow
from .dedup import find_duplicates
from .format import esc, fmt_price, format_line, format_listing, format_summary, long_id, short_id
from .geo import walk_minutes
from .http import BlockedError, LoginRequiredError, ParseError
from .models import Event, Listing, ScanResult
from .notify import Notifier
from .sources import build_sources
from .sources.base import Source
from .textnorm import detect_flags, detect_furnished, detect_price_includes, fold

log = logging.getLogger(__name__)

STICKY = ("description", "lat", "lon", "heating", "building_age", "elevator", "m2_net", "m2_gross",
          "furnished_src", "office", "floor", "floor_no", "listed_date", "rooms")


def _minutes_between(a: str, b: str) -> float:
    """İki UTC zaman damgası (YYYY-MM-DDTHH:MM:SSZ) arasındaki dakika; okunamazsa sonsuz."""
    try:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        return (datetime.strptime(b, fmt) - datetime.strptime(a, fmt)).total_seconds() / 60.0
    except (TypeError, ValueError):
        return float("inf")


class Pipeline:
    def __init__(self, cfg: Config, db: DB, notifier: Notifier, sources: Optional[list[Source]] = None):
        self.cfg = cfg
        self.db = db
        self.notifier = notifier
        self.sources: list[Source] = sources if sources is not None else build_sources(cfg)
        self.stations = cfg.stations
        self.lock = threading.Lock()
        self.scan_requested = threading.Event()
        self.last_summary: dict[str, Any] = {}

    # ------------------------------------------------------------------ ayar geçersiz kılmaları
    def budget(self) -> int:
        return int(self.db.get_setting("budget", self.cfg.budget))

    def set_budget(self, value: int) -> None:
        self.db.set_setting("budget", int(value))

    def neighborhoods(self) -> list[Neighborhood]:
        disabled = set(self.db.get_setting("disabled_neighborhoods", []) or [])
        out = [n for n in self.cfg.enabled_neighborhoods() if n.key not in disabled]
        for item in self.db.get_setting("extra_neighborhoods", []) or []:
            nb = Neighborhood(name=item["name"], station=item.get("station", ""),
                              hepsiemlak=item.get("hepsiemlak"), emlakjet=item.get("emlakjet"),
                              sahibinden=item.get("sahibinden"))
            if nb.key not in disabled and all(nb.key != o.key for o in out):
                out.append(nb)
        return out

    def add_neighborhood(self, name: str, station: str = "") -> Neighborhood:
        existing = self.cfg.neighborhood_by_key(name)
        disabled = set(self.db.get_setting("disabled_neighborhoods", []) or [])
        if existing:
            disabled.discard(existing.key)
            self.db.set_setting("disabled_neighborhoods", sorted(disabled))
            return existing
        st = self.stations.get(station) if station else None
        extra = [e for e in (self.db.get_setting("extra_neighborhoods", []) or []) if fold(e["name"]) != fold(name)]
        extra.append({"name": name, "station": st.name if st else station})
        self.db.set_setting("extra_neighborhoods", extra)
        disabled.discard(fold(name))
        self.db.set_setting("disabled_neighborhoods", sorted(disabled))
        return Neighborhood(name=name, station=st.name if st else station)

    def remove_neighborhood(self, name: str) -> bool:
        key = fold(name)
        extra = self.db.get_setting("extra_neighborhoods", []) or []
        new_extra = [e for e in extra if fold(e["name"]) != key]
        if len(new_extra) != len(extra):
            self.db.set_setting("extra_neighborhoods", new_extra)
            return True
        nb = self.cfg.neighborhood_by_key(name)
        if not nb:
            return False
        disabled = set(self.db.get_setting("disabled_neighborhoods", []) or [])
        disabled.add(nb.key)
        self.db.set_setting("disabled_neighborhoods", sorted(disabled))
        return True

    # ------------------------------------------------------------------ zenginleştirme / kriter
    def enrich(self, l: Listing, nb: Neighborhood) -> Listing:
        text = l.text_blob()
        l.furnished = detect_furnished(text, l.furnished_src)
        l.price_includes = detect_price_includes(text)
        flags = detect_flags(text, l.floor)
        max_walk = float(self.cfg.get("max_walk_m", default=1000))
        tol = float(self.cfg.get("walk_tolerance_m", default=300))
        speed = float(self.cfg.get("walk_speed_m_per_min", default=80))
        default_station = nb.station
        if l.district:
            dnb = self.cfg.neighborhood_by_key(l.district)
            if dnb and dnb.station:
                default_station = dnb.station
        if l.lat and l.lon:
            st, d = self.stations.nearest(l.lat, l.lon, lines=("M2",))
            if st:
                l.nearest_station = st.name
                l.distance_m = int(round(d))
                l.walk_minutes_est = walk_minutes(d, speed)
                l.distance_verified = True
                # "metro yakını" deyip M2'ye yürüme mesafesinde olmayan, Ankaray'a daha yakın ilan
                ank, d2 = self.stations.nearest(l.lat, l.lon, lines=("ANKARAY",))
                if ank and d2 < d and d > max_walk and "metro" in fold(text) and "ankaray_uyari" not in flags:
                    flags.append("ankaray_uyari")
                if d > max_walk + tol:
                    flags.append("uzak")
                elif d > max_walk:
                    flags.append("sinirda")
        if not l.distance_verified:
            l.nearest_station = default_station or None
            flags.append("mesafe_dogrulanmadi")
            if nb.require_distance:
                flags.append("mesafe_gerekli")
        if l.furnished == "unknown":
            flags.append("esya_belirsiz")
        l.flags = flags
        return l

    def evaluate(self, l: Listing, budget: Optional[int] = None) -> Listing:
        budget = budget or self.budget()
        tol = self.cfg.budget_tolerance_pct / 100.0
        l.matches = False
        l.match_tier = None
        l.flags = [f for f in l.flags if f != "pazarlikla"]
        via_mail = (l.extras or {}).get("via") == "mail"
        if not l.price:
            if not via_mail:
                return l
            tier = "uygun"  # e-posta bildirimi: fiyat çözülemese de kullanıcının kayıtlı araması zaten filtreli
        elif l.price <= budget:
            tier = "uygun"
        elif l.price <= budget * (1 + tol):
            tier = "pazarlikla"
        else:
            return l
        accept = set(self.cfg.get("furnished_accept", default=["full", "partial", "either"]) or [])
        if bool(self.cfg.get("include_unknown_furnished", default=False)):
            accept.add("unknown")
        if l.furnished not in accept:
            return l
        allowed = self.cfg.get("rooms_allowed", default=[]) or []
        if allowed and l.rooms and l.rooms not in allowed:
            return l
        exclude = set(self.cfg.get("exclude_flags", default=["gunluk", "oda", "uzak"]) or [])
        exclude.add("mesafe_gerekli")
        if exclude & set(l.flags):
            return l
        l.matches = True
        l.match_tier = tier
        if tier == "pazarlikla":
            l.flags.append("pazarlikla")
        return l

    def price_cap(self, budget: Optional[int] = None) -> int:
        budget = budget or self.budget()
        return int(budget * (1 + self.cfg.budget_tolerance_pct / 100.0))

    # ------------------------------------------------------------------ tarama
    def run_scan(self, trigger: str = "manual") -> dict[str, Any]:
        if not self.lock.acquire(blocking=False):
            return {"skipped": True, "reason": "tarama zaten sürüyor"}
        try:
            return self._run_scan(trigger)
        finally:
            self.scan_requested.clear()
            self.lock.release()

    def _run_scan(self, trigger: str) -> dict[str, Any]:
        started = utcnow()
        budget = self.budget()
        nbs = self.neighborhoods()
        summary: dict[str, Any] = {"started": started, "trigger": trigger, "budget": budget, "sources": {},
                                   "new": 0, "price_drop": 0, "removed": 0, "errors": [], "notified": 0}
        log.info("tarama başladı (%s): %d kaynak × %d mahalle, bütçe %s", trigger, len(self.sources), len(nbs), budget)
        summary["now_matching"] = self.reevaluate_all(budget)
        for src in self.sources:
            s_stats = {"neighborhoods": 0, "items": 0, "pages": 0, "errors": 0, "blocked": False}
            summary["sources"][src.name] = s_stats
            blocked_until = self.db.get_setting(f"blocked_until:{src.name}")
            if os.environ.get("M2KIRA_BLOCK_COOLDOWN_MIN", "").strip() == "0":
                blocked_until = None
            if blocked_until and blocked_until > started:
                s_stats["blocked"] = True
                summary["errors"].append(f"{src.name}: kısa süre önce engellendi, {blocked_until} UTC'ye kadar atlanıyor")
                continue
            # GitHub'da hem zamanlayıcı hem PC tetikleyebilir: siteyi `M2KIRA_MIN_INTERVAL_MIN` dakikadan sık tarama
            min_iv = float(os.environ.get("M2KIRA_MIN_INTERVAL_MIN", "") or 0)
            last_ok = self.db.get_setting(f"last_scan_ok:{src.name}")
            if min_iv > 0 and getattr(src, "site_scraper", True) and last_ok and _minutes_between(last_ok, started) < min_iv:
                s_stats["skipped"] = True
                log.info("%s: %s UTC'de tarandı; %g dk dolmadan yeniden taranmıyor", src.name, last_ok, min_iv)
                continue
            src.db = self.db  # tam geçiş planı, e-posta UID'si, güncel bütçe
            if hasattr(src, "begin_run"):
                src.begin_run()
            src_nbs = nbs if getattr(src, "per_neighborhood", True) else [Neighborhood(name=f"{src.name}-tum", station="")]
            for nb in src_nbs:
                if s_stats["blocked"]:
                    break
                try:
                    res = src.scan_neighborhood(nb)
                except (BlockedError, LoginRequiredError) as exc:
                    s_stats["blocked"] = True
                    s_stats["errors"] += 1
                    summary["errors"].append(f"{src.name}: {exc}")
                    self.db.log_scan(started, src.name, nb.name, 0, 0, False, str(exc))
                    self._mark_blocked(src)
                    self._access_notice(src, exc, nbs)
                    continue
                except ParseError as exc:
                    s_stats["errors"] += 1
                    summary["errors"].append(f"{src.name}/{nb.name}: {exc}")
                    self.db.log_scan(started, src.name, nb.name, 0, 0, False, str(exc))
                    self._notice(f"parse:{src.name}", 6, f"🛠 <b>Parser hata verdi</b> ({esc(src.name)} / {esc(nb.name)}):\n{esc(exc)}\n"
                                                        f"Site yapısı değişmiş olabilir; m2kira/sources/{src.name}.py güncellenmeli.")
                    continue
                except Exception as exc:  # noqa: BLE001
                    log.exception("tarama hatası %s/%s", src.name, nb.name)
                    s_stats["errors"] += 1
                    summary["errors"].append(f"{src.name}/{nb.name}: {exc}")
                    self.db.log_scan(started, src.name, nb.name, 0, 0, False, str(exc))
                    s_stats.setdefault("last_error", f"{nb.name}: {exc}")
                    continue
                try:
                    self._process_result(src, nb, res, budget, started, summary)
                except (BlockedError, LoginRequiredError) as exc:
                    s_stats["blocked"] = True
                    summary["errors"].append(f"{src.name}: {exc}")
                    self._mark_blocked(src)
                    self._access_notice(src, exc, nbs)
                s_stats["neighborhoods"] += 1
                s_stats["items"] += len(res.listings)
                s_stats["pages"] += res.pages
                if res.errors:
                    s_stats["errors"] += len(res.errors)
                    summary["errors"].extend(f"{src.name}/{nb.name}: {e}" for e in res.errors)
                self.db.log_scan(started, src.name, nb.name, res.pages, len(res.listings), res.complete,
                                 "; ".join(res.errors) if res.errors else None)
            # Ağ kesintisi gibi geçici hatalar tek seferde bildirilmez; kaynak art arda 2 taramada
            # hata verirse uyarılır. (Parser ve erişim engeli uyarıları yukarıda anında gider.)
            streak_key = f"error_streak:{src.name}"
            if s_stats.get("last_error"):
                streak = int(self.db.get_setting(streak_key, 0) or 0) + 1
                self.db.set_setting(streak_key, streak)
                if streak >= int(self.cfg.get("error_streak_before_notice", default=2)):
                    self._notice(f"error:{src.name}", 6, f"🛠 <b>Tarama hatası</b> ({esc(src.name)}, art arda {streak} tarama): "
                                                         f"{esc(s_stats['last_error'])}")
            elif not s_stats["blocked"]:
                self.db.set_setting(streak_key, 0)
            if not s_stats["blocked"] and s_stats["neighborhoods"]:
                self.db.set_setting(f"last_scan_ok:{src.name}", started)
        summary["notified"] = self._notify_events(budget)
        summary["finished"] = utcnow()
        self.last_summary = summary
        log.info("tarama bitti: yeni=%d düşüş=%d kalkan=%d bildirim=%d hata=%d", summary["new"], summary["price_drop"],
                 summary["removed"], summary["notified"], len(summary["errors"]))
        return summary

    def _process_result(self, src: Source, nb: Neighborhood, res: ScanResult, budget: int, started: str,
                        summary: dict[str, Any]) -> None:
        now = utcnow()
        cap = self.price_cap(budget)
        detail_budget = int(src.scfg.get("max_detail_fetch", 15))
        detail_for_coords = bool(src.scfg.get("detail_for_coords", True))
        per_nb = getattr(src, "per_neighborhood", True)
        scan_key = res.scan_key or nb.key
        seen_ids: list[str] = []
        prepared: list[tuple[Listing, Optional[dict[str, Any]], Neighborhood]] = []
        for l in res.listings:
            old = self.db.get(l.id)
            if old:
                for c in STICKY:
                    if getattr(l, c) in (None, "", []) and old.get(c) not in (None, ""):
                        setattr(l, c, old[c])
                if old.get("detail_fetched"):
                    l.detail_fetched = True
            l_nb = nb if per_nb else self._neighborhood_for(l, nb)
            l.neighborhood_key = l_nb.key if (per_nb or l_nb is not nb) else (fold(l.district) or None)
            l.scan_key = scan_key
            self.enrich(l, l_nb)
            self.evaluate(l, budget)
            prepared.append((l, old, l_nb))
            seen_ids.append(l.id)

        # detay: bütçe içindeki ama eşya durumu belirsiz / koordinatsız ilanlar için.
        # Kota tarama başına (kaynak bazında); ucuzdan pahalıya öncelik. Kalanlar sonraki taramada.
        # Erişim engeli (429/oturum) gelirse detay bırakılır ama liste verisi yine de yazılır.
        detail_counts = summary.setdefault("detail_fetched", {})
        fetched = int(detail_counts.get(src.name, 0))
        access_error: Optional[Exception] = None
        if src.supports_detail and detail_budget > 0:
            candidates = []
            for l, old, l_nb in prepared:
                if l.detail_fetched or not l.price or l.price > cap:
                    continue
                need = l.furnished == "unknown" or (detail_for_coords and not l.distance_verified and l.furnished != "none")
                if need:
                    candidates.append((l, l_nb))
            candidates.sort(key=lambda x: x[0].price or 0)
            for l, l_nb in candidates:
                if fetched >= detail_budget:
                    break
                try:
                    src.fetch_detail(l)
                    fetched += 1
                except (BlockedError, LoginRequiredError) as exc:
                    access_error = exc
                    break
                except ParseError as exc:
                    self._notice(f"parse-detail:{src.name}", 6, f"🛠 <b>Detay parser hata verdi</b> ({esc(src.name)}): {esc(exc)}")
                    fetched += 1
                    continue
                except Exception as exc:  # noqa: BLE001
                    log.warning("detay alınamadı %s: %s", l.id, exc)
                    fetched += 1
                    continue
                if not per_nb:
                    l_nb = self._neighborhood_for(l, nb)  # detaydan mahalle gelmiş olabilir
                    l.neighborhood_key = l_nb.key if l_nb is not nb else (fold(l.district) or None)
                self.enrich(l, l_nb)
                self.evaluate(l, budget)
        detail_counts[src.name] = fetched

        # veritabanı + olaylar
        for l, old, _ in prepared:
            old = self.db.upsert(l, now)
            if old is None:
                self.db.add_price(l.id, l.price, now)
                self.db.add_event(Event(listing_id=l.id, kind="new", new_price=l.price, created_at=now))
                summary["new"] += 1
                self._annotate_duplicates(l)
            else:
                if l.matches and not old.get("matches") and not old.get("notified_at") and old.get("active"):
                    # eskiden kriter dışıydı, şimdi uyuyor (ör. detaydan eşya/konum geldi)
                    self.db.add_event(Event(listing_id=l.id, kind="now_matches", new_price=l.price, created_at=now))
                if not old.get("active"):
                    self.db.add_event(Event(listing_id=l.id, kind="reappeared", old_price=old.get("price"),
                                            new_price=l.price, created_at=now))
                if l.price and old.get("price") != l.price:
                    self.db.add_price(l.id, l.price, now)
                    kind = "price_drop" if (old.get("price") or 0) > l.price else "price_up"
                    self.db.add_event(Event(listing_id=l.id, kind=kind, old_price=old.get("price"),
                                            new_price=l.price, created_at=now))
                    if kind == "price_drop":
                        summary["price_drop"] += 1
        # bölge medyanına göre "çok ucuz" bayrağı
        self._flag_cheap([l for l, _, _ in prepared])
        # yayından kalkma: yalnızca birimin tüm listeleri eksiksiz tarandıysa
        if res.complete and res.full_pass:
            threshold = int(self.cfg.get("missing_scans_before_removed", default=2))
            for r in self.db.mark_missing(src.name, scan_key, seen_ids, threshold=threshold, now=now):
                self.db.add_event(Event(listing_id=r["id"], kind="removed", old_price=r.get("price"), created_at=now))
                summary["removed"] += 1
            if hasattr(src, "mark_full_done"):
                src.mark_full_done(nb.key)
        if access_error is not None:
            raise access_error

    def _mark_blocked(self, src: Source) -> None:
        # GitHub Actions'ta her çalıştırma farklı IP'den gelir; bekleme orada M2KIRA_BLOCK_COOLDOWN_MIN=0 ile kapatılır
        env = os.environ.get("M2KIRA_BLOCK_COOLDOWN_MIN")
        mins = float(env) if env not in (None, "") else float(self.cfg.get("block_cooldown_min", default=45))
        if mins <= 0:
            self.db.set_setting(f"blocked_until:{src.name}", None)
            return
        until = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + mins * 60, tz=timezone.utc)
        self.db.set_setting(f"blocked_until:{src.name}", until.strftime("%Y-%m-%dT%H:%M:%SZ"))

    def reevaluate_all(self, budget: Optional[int] = None) -> int:
        """Tüm aktif ilanları güncel ayarlarla (bütçe, oda, eşya, yürüme, hariç bayraklar — siteden ya da
        Telegram'dan değişmiş olabilir) yeniden değerlendirir. Yeni uygun hale gelen ve daha önce hiç
        bildirilmemiş ilanlar için 'now_matches' olayı üretir. Döndürür: yeni uygun sayısı."""
        budget = budget or self.budget()
        now = utcnow()
        newly = 0
        for r in self.db.active_listings(include_hidden=True):
            l = row_to_listing(r)
            keep = [f for f in (r.get("flags") or []) if f.startswith("kopya:") or f == "fiyat_cok_dusuk"]
            nb = self.cfg.neighborhood_by_key(l.neighborhood_key or "") or self._neighborhood_for(
                l, Neighborhood(name=l.neighborhood_key or "?", station=r.get("nearest_station") or ""))
            self.enrich(l, nb)
            self.evaluate(l, budget)
            l.flags = l.flags + [f for f in keep if f not in l.flags]
            changed = {}
            for k in ("matches", "match_tier", "flags", "nearest_station", "distance_m", "walk_minutes_est",
                      "distance_verified", "furnished", "price_includes"):
                nv, ov = getattr(l, k), r.get(k)
                if (bool(nv) if k in ("matches", "distance_verified") else nv) != (bool(ov) if k in ("matches", "distance_verified") else ov):
                    changed[k] = nv
            if changed:
                self.db.update_fields(l.id, **changed)
            if l.matches and not r.get("matches") and not r.get("notified_at"):
                self.db.add_event(Event(listing_id=l.id, kind="now_matches", new_price=l.price, created_at=now))
                newly += 1
        if newly:
            log.info("yeniden değerlendirme: %d ilan artık kriterlere uyuyor", newly)
        return newly

    def _neighborhood_for(self, l: Listing, fallback: Neighborhood) -> Neighborhood:
        """Birleşik aramadan gelen ilanı (sahibinden, e-posta) config'teki mahalleye eşler."""
        if l.district:
            found = self.cfg.neighborhood_by_key(l.district)
            if found:
                return found
            for extra in self.neighborhoods():
                if extra.key == fold(l.district):
                    return extra
        return fallback

    def _flag_cheap(self, listings: list[Listing]) -> None:
        ratio = float(self.cfg.get("cheap_ratio", default=0.6))
        for l in listings:
            if not l.price or not l.neighborhood_key:
                continue
            key = l.neighborhood_key
            med = self.db.median_price(key, l.rooms) or self.db.median_price(key)
            if not med:
                continue
            cheap = l.price < ratio * med
            flags = [f for f in l.flags if f != "fiyat_cok_dusuk"]
            if cheap:
                flags.append("fiyat_cok_dusuk")
            if flags != l.flags:
                l.flags = flags
                self.db.update_fields(l.id, flags=flags)

    def _annotate_duplicates(self, l: Listing) -> None:
        cands = self.db.active_listings(include_hidden=True)
        dups = find_duplicates(l.to_dict(), cands)
        if dups:
            flags = l.flags + [f"kopya:{short_id(d)}" for d in dups]
            l.flags = flags
            self.db.update_fields(l.id, flags=flags, dup_of=dups)

    # ------------------------------------------------------------------ bildirimler
    def _notice(self, key: str, min_hours: float, text: str) -> None:
        if self.db.notice_due(key, min_hours):
            try:
                self.notifier.send(text, subject="m2kira uyarı")
            except Exception as exc:  # noqa: BLE001
                log.error("uyarı gönderilemedi: %s", exc)

    def _access_notice(self, src: Source, exc: Exception, nbs: list[Neighborhood]) -> None:
        links = []
        for nb in nbs:
            for u in src.manual_urls(nb):
                links.append(f"• {esc(nb.name)}: {esc(u)}")
        kind = "oturum istiyor" if isinstance(exc, LoginRequiredError) else "erişimi engelledi"
        text = (f"⛔ <b>{esc(src.name)} {kind}</b>\n{esc(exc)}\n\n"
                f"Bu kaynağı elle kontrol edin (linkler):\n" + "\n".join(links[:30]))
        self._notice(f"access:{src.name}", 24 if isinstance(exc, LoginRequiredError) else 6, text)

    def _notify_events(self, budget: int) -> int:
        events = self.db.pending_events()
        if not events:
            return 0
        notify_removed = bool(self.cfg.get("notify_removed", default=True))
        # siteden: yalnız bu duraklar için bildir (boş = hepsi); favoriler her zaman (fiyat düşüşü / kalkma)
        stations = set(self.cfg.get("notify_stations", default=[]) or [])
        favorites = set(self.cfg.get("favorites", default=[]) or [])
        cards: list[tuple[dict[str, Any], dict[str, Any]]] = []
        done: list[int] = []
        for ev in events:
            done.append(ev.id)  # type: ignore[arg-type]
            l = self.db.get(ev.listing_id)
            if not l or l.get("hidden"):
                continue
            evd = {"kind": ev.kind, "old_price": ev.old_price, "new_price": ev.new_price}
            fav = l["id"] in favorites
            if fav:
                evd["fav"] = True
            if ev.kind in ("new", "reappeared", "price_drop", "now_matches"):
                if fav and ev.kind == "price_drop" and l.get("active"):
                    cards.append((l, evd))
                elif l.get("matches") and l.get("active") and (not stations or l.get("nearest_station") in stations or fav):
                    cards.append((l, evd))
            elif ev.kind == "removed":
                if (notify_removed and l.get("notified_at")) or fav:
                    cards.append((l, evd))
        sent = 0
        compact_threshold = int(self.cfg.get("compact_threshold", default=12))
        if len(cards) > compact_threshold:
            # ilk tarama / çok sayıda değişiklik: tek bir kompakt liste
            lines = [f"<b>📬 {len(cards)} değişiklik</b> (bütçe {fmt_price(budget)})"]
            link = self.web_link(nw=24, sort="new")
            if link:
                lines.append(f'🔎 <a href="{esc(link)}">Filtre sayfasında aç</a>')
            for l, evd in sorted(cards, key=lambda c: (c[0].get('price') or 0)):
                head = {"new": "🆕", "reappeared": "♻️", "price_drop": "💸", "removed": "❌", "now_matches": "✅"}.get(evd["kind"], "")
                lines.append(head + " " + format_line(l))
            try:
                self.notifier.send("\n".join(lines), subject=f"m2kira: {len(cards)} değişiklik")
                sent = len(cards)
            except Exception as exc:  # noqa: BLE001
                log.error("toplu bildirim gönderilemedi: %s", exc)
        else:
            for l, evd in cards:
                try:
                    text = format_listing(l, evd, budget)
                    img = str((l.get("extras") or {}).get("img") or "")
                    if evd["kind"] != "removed" and img.startswith("https://"):
                        self.notifier.send_photo(img, text, subject=f"m2kira: {evd['kind']}")
                    else:
                        self.notifier.send(text, subject=f"m2kira: {evd['kind']}")
                    sent += 1
                except Exception as exc:  # noqa: BLE001
                    log.error("bildirim gönderilemedi (%s): %s", l.get("id"), exc)
        now = utcnow()
        for l, evd in cards:
            if evd["kind"] != "removed":
                self.db.set_notified(l["id"], now)
        self.db.mark_events_notified(done)
        return sent

    # ------------------------------------------------------------------ özet / liste / durum
    def matching_listings(self, max_price: Optional[int] = None, station: Optional[str] = None,
                          neighborhood: Optional[str] = None, tier: Optional[str] = None) -> list[dict[str, Any]]:
        rows = self.db.active_listings(matches_only=True)
        if max_price:
            rows = [r for r in rows if r.get("price") and r["price"] <= max_price]
        if station:
            rows = [r for r in rows if fold(station) in fold(r.get("nearest_station"))]
        if neighborhood:
            rows = [r for r in rows if fold(neighborhood) in fold(r.get("district")) or fold(neighborhood) in fold(r.get("neighborhood_key"))]
        if tier:
            rows = [r for r in rows if r.get("match_tier") == tier]
        return rows

    def summary_text(self, title: str = "Günlük özet", limit: int = 40) -> str:
        budget = self.budget()
        rows = self.matching_listings(max_price=budget)
        return format_summary(rows, budget, title=title, limit=limit)

    # ------------------------------------------------------------------ filtre sayfası linkleri
    def web_link(self, **state: Any) -> Optional[str]:
        base = str(self.cfg.get("web", "url", default="") or "").strip()
        if not base:
            return None
        from urllib.parse import urlencode
        params = {k: (",".join(v) if isinstance(v, (list, tuple)) else v) for k, v in state.items() if v not in (None, "", [])}
        return base + ("#" + urlencode(params) if params else "")

    def station_overview(self) -> str:
        """Hat sırasıyla durak durak uygun ilan sayısı, en ucuz ve medyan fiyat (+ sayfa linki)."""
        budget = self.budget()
        rows = self.matching_listings(max_price=int(budget * (1 + self.cfg.budget_tolerance_pct / 100.0)))
        lines = [f"<b>🚇 Durak durak</b> (bütçe {fmt_price(budget)} +%{self.cfg.budget_tolerance_pct:g})"]
        unknown = 0
        by_station: dict[str, list[int]] = {}
        for r in rows:
            if r.get("nearest_station") and r.get("price"):
                by_station.setdefault(r["nearest_station"], []).append(r["price"])
            else:
                unknown += 1
        for s in (x for x in self.stations.stations if x.line == "M2"):
            prices = by_station.get(s.name, [])
            if not prices:
                lines.append(f"▫️ {esc(s.name)}: —")
                continue
            link = self.web_link(st=s.name)
            name = f'<a href="{esc(link)}">{esc(s.name)}</a>' if link else esc(s.name)
            lines.append(f"🔸 {name}: <b>{len(prices)}</b> ilan · en ucuz {fmt_price(min(prices))} · medyan "
                         f"{fmt_price(int(statistics.median(prices)))}")
        if unknown:
            lines.append(f"(+{unknown} ilanın durağı belirsiz)")
        link = self.web_link()
        if link:
            lines.append(f'\n🔎 <a href="{esc(link)}">Filtre sayfası</a> — durak, fiyat, oda, yürüme, işe ulaşım')
        return "\n".join(lines)

    def send_daily_summary(self) -> None:
        text = self.summary_text()
        extra = self.matching_listings(tier="pazarlikla")
        if extra:
            text += "\n\n<b>🤝 Bütçe üstü, pazarlıkla</b>\n" + "\n".join(format_line(l) for l in extra[:10])
        link = self.web_link()
        if link:
            text += f'\n\n🔎 <a href="{esc(link)}">Filtre sayfası</a> (durak durak, harita, işe ulaşım süresi)'
        self.notifier.send(text, subject="m2kira günlük özet")
        self.db.set_setting("summary_sent_on", datetime.now().date().isoformat())

    def daily_summary_if_due(self, ignore_time: bool = False, now: Optional[datetime] = None) -> bool:
        """Günlük özeti günde bir kez gönderir. GitHub'ın zamanlanmış çalıştırması düşerse özet, özet saatinden
        sonraki ilk çalıştırmada (zamanlayıcı ya da PC tetiklemesi) gider. Saat yerel saattir (TZ)."""
        now = now or datetime.now()
        if self.db.get_setting("summary_sent_on") == now.date().isoformat():
            return False
        hh, mm = (int(x) for x in str(self.cfg.get("daily_summary_time", default="09:00")).split(":")[:2])
        if not ignore_time and (now.hour, now.minute) < (hh, mm):
            return False
        self.send_daily_summary()
        self.db.set_setting("summary_sent_on", now.date().isoformat())
        return True

    def status_text(self) -> str:
        c = self.db.counts()
        last = self.db.last_scan_info()
        lines = ["<b>Durum</b>", f"Bütçe: {fmt_price(self.budget())} (+%{self.cfg.budget_tolerance_pct:g} pazarlık payı)",
                 f"Mahalleler: {len(self.neighborhoods())} · Kaynaklar: {', '.join(s.name for s in self.sources) or '-'}",
                 f"İlan: toplam {c['total']}, aktif {c['active']}, uygun {c['matching']}"]
        if last:
            lines.append(f"Son tarama: {esc(last['started_at'])} UTC · {last['items'] or 0} ilan · {last['pages'] or 0} sayfa · {last['errors'] or 0} hata")
        if self.last_summary.get("errors"):
            lines.append("Son hatalar:\n" + "\n".join("• " + esc(e) for e in self.last_summary["errors"][:8]))
        return "\n".join(lines)

    def hide(self, short: str, hidden: bool = True) -> Optional[str]:
        lid = long_id(short) if ":" in short else None
        if lid and self.db.get(lid):
            self.db.set_hidden(lid, hidden)
            return lid
        rows = self.db.find_by_source_id(short)
        if rows:
            for r in rows:
                self.db.set_hidden(r["id"], hidden)
            return rows[0]["id"]
        return None

    def close(self) -> None:
        for s in self.sources:
            try:
                s.close()
            except Exception:
                pass
