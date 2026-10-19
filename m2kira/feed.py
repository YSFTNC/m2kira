"""PC -> GitHub besleme: hepsiemlak (Cloudflare GitHub IP'lerini engelliyor) ve sahibinden (giriş + bot
koruması) yalnızca ev internetinden / gerçek tarayıcıdan erişilebildiği için PC açıkken taranır, sonuç reponun
`feed` dalına JSON olarak yazılır ve GitHub Actions işi tetiklenir. GitHub tarafında `hepsiemlak_feed` ve
`sahibinden_feed` kaynakları bu dosyaları okur; bildirim/kopya/web sitesi tek yerden yönetilir.

    python main.py feed-push                     # hepsiemlak + sahibinden (Görev Zamanlayıcı bunu çalıştırır)
    python main.py feed-push --only sahibinden   # tek kaynak
    python main.py feed-push --no-push           # yalnız tara, data/feed/*.json'a yaz
"""
from __future__ import annotations

import base64
import json
import logging
import os
import random
import shutil
import time
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

from .config import Config
from .db import DB
from .http import BlockedError, LoginRequiredError, ParseError
from .models import Listing

log = logging.getLogger(__name__)
DROP_FIELDS = {"matches", "match_tier", "flags", "nearest_station", "distance_m", "walk_minutes_est",
               "distance_verified", "furnished", "price_includes", "scan_key"}
# sahibinden önce: birkaç dakika sürer ve ilanları en hızlı kapılan kaynak; yavaş bir hepsiemlak geçişi
# (429 beklemeleri) onu geciktirmesin ya da görev süre sınırında aç bırakmasın.
FEED_SOURCES = ("sahibinden", "hepsiemlak")
# sahibinden detayından saklanan alanlar (koordinat, açıklama, kat, ...)
SB_DETAIL_FIELDS = ("lat", "lon", "description", "m2_gross", "m2_net", "floor", "floor_no", "building_age", "heating",
                    "elevator", "owner_type", "listed_date", "district", "furnished_src")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def feed_cfg(cfg: Config, source: str = "hepsiemlak") -> dict[str, Any]:
    d = dict(cfg.source_cfg(f"{source}_feed"))
    base = dict(cfg.source_cfg("hepsiemlak_feed"))
    d.setdefault("repo", base.get("repo", "YSFTNC/m2kira"))
    d.setdefault("branch", base.get("branch", "feed"))
    d.setdefault("path", f"feed/{source}.json")
    d.setdefault("max_age_hours", 3)
    return d


def listing_to_feed(l: Listing) -> dict[str, Any]:
    d = l.to_dict()
    for k in DROP_FIELDS:
        d.pop(k, None)
    d.pop("id", None)
    d["description"] = (d.get("description") or "")[:600]
    return d


def sync_budget_from_web(cfg: Config, db: DB) -> None:
    """GitHub'daki güncel bütçeyi (siteden / /butce ile değişmiş olabilir) yayınlanan data.json'dan al."""
    url = str(cfg.get("web", "url", default="") or "").rstrip("/")
    if not url:
        return
    try:
        r = requests.get(url + "/data.json", timeout=20)
        if r.ok:
            b = int(r.json().get("budget") or 0)
            if b > 0:
                db.set_setting("budget", b)
    except Exception as exc:  # noqa: BLE001
        log.debug("bütçe alınamadı: %s", exc)


def _payload(source: str, units: list[dict[str, Any]], errors: list[str]) -> dict[str, Any]:
    return {"generated": utcnow(), "source": source, "units": units, "errors": errors,
            "listings": sum(len(u["listings"]) for u in units)}


# ------------------------------------------------------------------ hepsiemlak
def collect_hepsiemlak(cfg: Config, db: DB) -> dict[str, Any]:
    """hepsiemlak'ı (hızlı/tam geçiş planıyla) tarar."""
    from .sources.hepsiemlak import HepsiemlakSource
    src = HepsiemlakSource(cfg)
    src.db = db
    src.begin_run()
    units: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        for nb in cfg.enabled_neighborhoods():
            if not nb.slug_for("hepsiemlak"):
                continue
            try:
                res = src.scan_neighborhood(nb)
            except (BlockedError, LoginRequiredError) as exc:
                errors.append(f"{nb.name}: {exc}")
                log.warning("hepsiemlak engellendi, tarama durdu: %s", exc)
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{nb.name}: {exc}")
                log.warning("hepsiemlak %s: %s", nb.name, exc)
                continue
            units.append({"nb": nb.key, "complete": res.complete, "full_pass": res.full_pass, "pages": res.pages,
                          "errors": res.errors, "listings": [listing_to_feed(l) for l in res.listings]})
            if res.complete and res.full_pass:
                src.mark_full_done(nb.key)
    finally:
        src.close()
    return _payload("hepsiemlak", units, errors)


# keep the old name for callers/tests
collect = collect_hepsiemlak


# ------------------------------------------------------------------ sahibinden
def _detail_cache_path(cfg: Config):
    return cfg.data_dir / "feed" / "sahibinden_details.json"


def _load_detail_cache(cfg: Config) -> dict[str, dict[str, Any]]:
    p = _detail_cache_path(cfg)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def _save_detail_cache(cfg: Config, cache: dict[str, dict[str, Any]]) -> None:
    # 30 gündür görülmeyenleri at
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cache = {k: v for k, v in cache.items() if (v.get("seen") or "") >= cutoff}
    p = _detail_cache_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def collect_sahibinden(cfg: Config, db: DB, max_details: Optional[int] = None) -> dict[str, Any]:
    """Kullanıcının giriş yapılmış Chrome profiliyle (görünmez) sahibinden birleşik aramasını tarar; konum
    için ilan detaylarını tarama başına sınırlı sayıda çekip önbellekte tutar."""
    from .chrome import ChromeSession
    from .sources.sahibinden import SahibindenSource
    scfg = cfg.source_cfg("sahibinden_feed")
    port = int(str(cfg.source_cfg("sahibinden").get("cdp_url", "http://127.0.0.1:9222")).rsplit(":", 1)[-1].strip("/") or 9222)
    max_details = int(max_details if max_details is not None else scfg.get("max_detail_fetch", 15))
    cache = _load_detail_cache(cfg)
    units: list[dict[str, Any]] = []
    errors: list[str] = []
    now = utcnow()
    src = None
    try:
        with ChromeSession(cfg.data_dir / "chrome-profile", port=port, headless=bool(scfg.get("headless", True))):
            src = SahibindenSource(cfg)
            src.db = db
            src.mode = "cdp"
            src.headed_fallback = False
            src.browser.cdp_url = f"http://127.0.0.1:{port}"
            res = src.scan_neighborhood(None)   # liste sayfası giriş isterse burada LoginRequiredError -> uyarı
            # yeni ilanların detayı (koordinat, açıklama): en yeniler önce. 19.10.2026: ~30 detaydan sonra
            # sahibinden geçici bir giriş duvarı gösterdi (oturum geçerliydi) -> tarama başına sınır + rastgele
            # bekleme; duvar çıkarsa detay bırakılır ama liste verisi yine gönderilir.
            need = [l for l in res.listings if not (cache.get(l.id) or {}).get("lat")
                    and int((cache.get(l.id) or {}).get("attempts", 0)) < 3]
            need.sort(key=lambda l: (l.listed_date or ""), reverse=True)
            fetched = 0
            for l in need[:max_details]:
                time.sleep(random.uniform(2.0, 7.0))
                prev = cache.get(l.id) or {}
                try:
                    src.fetch_detail(l)
                except (BlockedError, LoginRequiredError) as exc:
                    log.warning("sahibinden detay duvarı (%s); bu tarama için detay bırakıldı (%d alındı)", exc, fetched)
                    cache[l.id] = dict(prev, seen=now, attempts=int(prev.get("attempts", 0)) + 1)
                    break
                except ParseError as exc:
                    log.warning("sahibinden detay ayrıştırılamadı %s: %s", l.id, exc)
                    cache[l.id] = dict(prev, seen=now, error=str(exc)[:120], attempts=int(prev.get("attempts", 0)) + 1)
                    continue
                except Exception as exc:  # noqa: BLE001
                    log.warning("sahibinden detay alınamadı %s: %s", l.id, exc)
                    cache[l.id] = dict(prev, seen=now, attempts=int(prev.get("attempts", 0)) + 1)
                    continue
                entry = {k: getattr(l, k) for k in SB_DETAIL_FIELDS if getattr(l, k) not in (None, "")}
                for k in ("aidat", "deposit", "floor_count"):
                    if l.extras.get(k):
                        entry[k] = l.extras[k]
                entry["seen"] = now
                cache[l.id] = entry
                fetched += 1
            # önbellekteki detayı tüm ilanlara uygula
            for l in res.listings:
                c = cache.get(l.id)
                if c is not None:
                    c["seen"] = now
                if not c or not c.get("lat"):
                    continue
                for k in SB_DETAIL_FIELDS:
                    if k in c and k != "furnished_src":
                        setattr(l, k, c[k])
                if c.get("furnished_src") is not None:
                    l.furnished_src = c["furnished_src"]
                for k in ("aidat", "deposit", "floor_count"):
                    if k in c:
                        l.extras[k] = c[k]
                l.detail_fetched = True
            log.info("sahibinden: %d ilan (%d sayfa), %d yeni detay, önbellekte %d", len(res.listings), res.pages,
                     fetched, len(cache))
            units.append({"nb": "sahibinden-arama", "complete": res.complete, "full_pass": True, "pages": res.pages,
                          "errors": res.errors, "listings": [listing_to_feed(l) for l in res.listings]})
    except (LoginRequiredError, BlockedError) as exc:
        errors.append(str(exc))
        log.warning("sahibinden: %s", exc)
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        log.exception("sahibinden taraması başarısız")
    finally:
        if src is not None:
            src.close()
        _save_detail_cache(cfg, cache)
    return _payload("sahibinden", units, errors)


def _is_login_error(errors: list[str]) -> bool:
    return any("oturum" in e.lower() or "giriş" in e.lower() or "giris" in e.lower() for e in errors)


def _send_pc_notice(cfg: Config, text: str, subject: str) -> None:
    try:
        from .notify import build_notifier
        build_notifier(cfg).send(text, subject=subject)
    except Exception as exc:  # noqa: BLE001
        log.warning("uyarı gönderilemedi: %s", exc)


FEED_HINTS = {
    "sahibinden": ("Bilgisayarda proje klasöründe <code>python main.py sahibinden-chrome</code> çalıştır; açılan Chrome'da "
                   "sahibinden'i aç, doğrulama ya da giriş isterse geç, sonra pencereyi kapat."),
    "hepsiemlak": ("Genelde hepsiemlak'ın hız sınırı ya da Cloudflare doğrulamasıdır ve birkaç saat içinde kendiliğinden "
                   "düzelir. Sürerse bilgisayarın internet bağlantısına bak."),
}


def notify_feed_problem(cfg: Config, db: DB, source: str, payload: dict[str, Any]) -> None:
    """PC'de bir kaynak hiç taranamadıysa Telegram'a haber verir: sahibinden oturumu düştüyse hemen, diğer
    hatalarda üst üste 2 başarısız çalıştırmadan sonra. Her uyarı en fazla günde bir; başarılı taramada sayaç sıfırlanır."""
    key = f"feed_fail_streak:{source}"
    if payload.get("units"):
        if db.get_setting(key, 0):
            db.set_setting(key, 0)
        return
    streak = int(db.get_setting(key, 0) or 0) + 1
    db.set_setting(key, streak)
    errors = [str(e) for e in payload.get("errors") or []]
    if source == "sahibinden" and _is_login_error(errors):
        if db.notice_due("sahibinden-login", 24):
            _send_pc_notice(cfg,
                "🔑 <b>sahibinden oturumu düştü</b>\nPC'de proje klasöründe şunu çalıştırıp açılan Chrome'da giriş yap:\n"
                "<code>python main.py sahibinden-chrome</code>\nGiriş yapınca pencereyi kapatabilirsin; sonraki taramada "
                "sahibinden ilanları siteye yine gelir.", "m2kira sahibinden")
        return
    if streak < 2 or not db.notice_due(f"feed-fail:{source}", 24):
        return
    from .format import esc
    detail = esc("; ".join(errors)[:300] or "bilinmeyen hata")
    _send_pc_notice(cfg, f"⚠️ <b>{esc(source)} bilgisayardan taranamıyor</b> ({streak} çalıştırmadır)\n{detail}\n"
                         f"{FEED_HINTS.get(source, '')}", f"m2kira {source}")


# ------------------------------------------------------------------ GitHub
def gh_exe() -> Optional[str]:
    exe = shutil.which("gh")
    if exe:
        return exe
    for c in (r"C:\Program Files\GitHub CLI\gh.exe", r"C:\Program Files (x86)\GitHub CLI\gh.exe"):
        if os.path.exists(c):
            return c
    return None


def _gh(args: list[str], input_file: Optional[str] = None) -> subprocess.CompletedProcess:
    exe = gh_exe()
    if not exe:
        raise RuntimeError("GitHub CLI (gh) bulunamadı")
    cmd = [exe] + args + (["--input", input_file] if input_file else [])
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def push(cfg: Config, payload: dict[str, Any]) -> str:
    fc = feed_cfg(cfg, payload.get("source", "hepsiemlak"))
    repo, branch, path = fc["repo"], fc["branch"], fc["path"]
    r = _gh(["api", f"repos/{repo}/git/ref/heads/{branch}"])
    if r.returncode != 0:
        main_sha = _gh(["api", f"repos/{repo}/git/ref/heads/main", "--jq", ".object.sha"]).stdout.strip()
        if not main_sha:
            raise RuntimeError(f"main dalı okunamadı: {r.stderr.strip()[:200]}")
        c = _gh(["api", "-X", "POST", f"repos/{repo}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={main_sha}"])
        if c.returncode != 0:
            raise RuntimeError(f"{branch} dalı oluşturulamadı: {c.stderr.strip()[:200]}")
    sha = _gh(["api", f"repos/{repo}/contents/{path}?ref={branch}", "--jq", ".sha"]).stdout.strip()
    body = {
        "message": f"{payload.get('source')} beslemesi {payload['generated']} ({payload['listings']} ilan)",
        "content": base64.b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha and not sha.startswith("{"):
        body["sha"] = sha
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(body, fh)
        tmp = fh.name
    try:
        p = _gh(["api", "-X", "PUT", f"repos/{repo}/contents/{path}"], input_file=tmp)
    finally:
        os.unlink(tmp)
    if p.returncode != 0:
        raise RuntimeError(f"besleme gönderilemedi: {p.stderr.strip()[:300]}")
    return f"{repo}@{branch}:{path}"


def trigger(cfg: Config, sources: str = "hepsiemlak_feed,sahibinden_feed") -> bool:
    fc = feed_cfg(cfg)
    r = _gh(["workflow", "run", "scan.yml", "--repo", fc["repo"], "-f", f"sources={sources}"])
    if r.returncode != 0:
        log.warning("GitHub işi tetiklenemedi: %s", r.stderr.strip()[:200])
    return r.returncode == 0
