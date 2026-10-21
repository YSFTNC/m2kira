"""Filtre sayfası için veri dışa aktarımı (GitHub Pages).

`python main.py export-web --out _site` -> _site/index.html (sabit arayüz) + _site/data.json (ilanlar).
Arayüz tamamen tarayıcıda filtreler; sunucu gerekmez. Her taramadan sonra yeniden üretilir.
"""
from __future__ import annotations

import json
import shutil
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .db import DB
from .textnorm import FLAG_LABELS, FURNISHED_LABELS

TEMPLATE = Path(__file__).resolve().parent / "web" / "index.html"
DESC_SNIPPET = 400


def m2_line(cfg: Config) -> list[dict[str, Any]]:
    """M2 durakları hat sırasıyla (config'teki sıra Kızılay -> Koru)."""
    out = []
    for i, s in enumerate(s for s in cfg.stations.stations if s.line == "M2"):
        out.append({"name": s.name, "lat": s.lat, "lon": s.lon, "i": i})
    return out


def commute_targets(cfg: Config) -> list[dict[str, Any]]:
    targets = cfg.get("commute", "targets", default=None) or [
        {"name": "Milli Kütüphane", "short": "MK", "station": "Milli Kütüphane", "extra_min": 0},
    ]
    return [dict(t) for t in targets]


def commute_minutes(station: Optional[str], walk_min: Optional[int], verified: bool, cfg: Config,
                    line: list[dict[str, Any]], targets: list[dict[str, Any]]) -> dict[str, Any]:
    """Evden hedefe tahmini kapıdan kapıya süre: yürüme + bekleme + durak sayısı × dk/durak + ek (otobüs vb.)."""
    if not station:
        return {}
    idx = {s["name"]: s["i"] for s in line}
    if station not in idx:
        return {}
    per_stop = float(cfg.get("commute", "ride_min_per_stop", default=2.2))
    wait = float(cfg.get("commute", "wait_min", default=3))
    walk = walk_min if (verified and walk_min is not None) else float(cfg.get("commute", "unknown_walk_min", default=10))
    out: dict[str, Any] = {}
    for t in targets:
        tgt = t.get("station")
        if tgt not in idx:
            continue
        stops = abs(idx[station] - idx[tgt])
        total = walk + (wait + stops * per_stop if stops else 0) + float(t.get("extra_min", 0))
        out[t.get("short") or t["name"]] = int(round(total))
    return out


# emlakjet'in görsel sunucusu (Cloudflare) tarayıcının başka siteden gelen görsel isteklerini
# (Sec-Fetch-Site: cross-site) 403 ile reddediyor; kart fotoğrafı yerine "fotoğraflar emlakjet'te" gösterilir.
NO_HOTLINK_SOURCES = {"emlakjet"}


def build_payload(cfg: Config, db: DB, budget: Optional[int] = None) -> dict[str, Any]:
    budget = int(budget or db.get_setting("budget", cfg.budget))
    tol = float(cfg.budget_tolerance_pct)
    line = m2_line(cfg)
    targets = commute_targets(cfg)
    rows = db.active_listings(include_hidden=True)

    # fiyat geçmişi (tek sorgu)
    hist: dict[str, list[int]] = {}
    for lid, price in db.conn.execute("SELECT listing_id, price FROM price_history ORDER BY seen_at"):
        if price is not None:
            h = hist.setdefault(lid, [])
            if not h or h[-1] != price:
                h.append(int(price))

    items = []
    for r in rows:
        extras = r.get("extras") or {}
        prev = None
        h = hist.get(r["id"], [])
        if len(h) >= 2 and h[-1] < h[-2]:
            prev = h[-2]
        elif extras.get("previous_price") and r.get("price") and extras["previous_price"] > r["price"]:
            prev = int(extras["previous_price"])
        desc = (r.get("description") or "").replace("\n", " ")
        items.append({
            "id": r["id"],
            "src": r["source"],
            "url": r.get("url"),
            "t": r.get("title") or "",
            "p": r.get("price"),
            "pp": prev,
            "inc": r.get("price_includes") or [],
            "r": r.get("rooms"),
            "m2": r.get("m2_gross"),
            "m2n": r.get("m2_net"),
            "fl": r.get("floor"),
            "fn": r.get("floor_no"),
            "age": r.get("building_age"),
            "heat": r.get("heating"),
            "el": r.get("elevator"),
            "fur": r.get("furnished") or "unknown",
            "d": r.get("district"),
            "st": r.get("nearest_station"),
            "dm": r.get("distance_m"),
            "wm": r.get("walk_minutes_est"),
            "v": bool(r.get("distance_verified")),
            "lat": round(r["lat"], 6) if r.get("lat") else None,
            "lon": round(r["lon"], 6) if r.get("lon") else None,
            "fs": (r.get("first_seen") or "")[:16],
            "ld": r.get("listed_date"),
            "of": r.get("office") or r.get("owner_type"),
            "cat": r.get("category"),
            "fg": [f for f in (r.get("flags") or []) if not f.startswith("kopya:")],
            "dup": [f.split(":", 1)[1] for f in (r.get("flags") or []) if f.startswith("kopya:")],
            "ok": bool(r.get("matches")),
            "tier": r.get("match_tier"),
            "hid": bool(r.get("hidden")),
            "aid": extras.get("aidat"),
            "img": (extras.get("img") if str(extras.get("img") or "").startswith("https://")
                    and r["source"] not in NO_HOTLINK_SOURCES else None),
            "ph": h if len(h) > 1 else None,
            "desc": desc[:DESC_SNIPPET],
            "cm": commute_minutes(r.get("nearest_station"), r.get("walk_minutes_est"),
                                  bool(r.get("distance_verified")), cfg, line, targets),
        })

    # durak özetleri (uygun ilanlar üzerinden)
    stats = {}
    for s in line:
        prices = [i["p"] for i in items if i["ok"] and not i["hid"] and i["st"] == s["name"] and i["p"]]
        stats[s["name"]] = {
            "n": len(prices),
            "min": min(prices) if prices else None,
            "med": int(statistics.median(prices)) if prices else None,
        }
    last = db.last_scan_info() or {}
    from .site_settings import effective
    fc = cfg.source_cfg("hepsiemlak_feed")
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_scan": last.get("finished_at") or last.get("started_at"),
        "settings": effective(cfg, db),
        "status": source_status(db),
        "feed_generated": {s: db.get_setting(f"feed_processed:{s}") for s in ("hepsiemlak", "sahibinden")},
        "neighborhoods": [{"name": n.name, "key": n.key, "station": n.station, "enabled": n.enabled}
                          for n in cfg.neighborhoods],
        "repo": {"name": str(fc.get("repo", "YSFTNC/m2kira")), "branch": str(fc.get("branch", "feed")),
                 "settings_path": "feed/settings.json", "workflow": "scan.yml"},
        "schedule": {"every_hours": cfg.scan_interval_hours, "every_min": round(cfg.scan_interval_hours * 60), "summary": str(cfg.get("daily_summary_time", default="09:00"))},
        "telegram_bot": str(cfg.get("web", "telegram_bot", default="") or ""),
        "feed_max_age_hours": float(fc.get("max_age_hours", 3)),
        "flag_keys": ["gunluk", "oda", "uzak", "kisit", "kot_bodrum", "acil", "kapora", "depozitosuz",
                      "kisa_sureli", "ankaray_uyari", "fiyat_cok_dusuk", "esya_belirsiz"],
        "new24": sum(1 for i in items if i["ok"] and i["fs"] and i["fs"] >= _hours_ago(24)),
        "budget": budget,
        "tol": tol,
        "max_walk_m": int(cfg.get("max_walk_m", default=1000)),
        "line": line,
        "targets": targets,
        "stats": stats,
        "flag_labels": FLAG_LABELS,
        "fur_labels": FURNISHED_LABELS,
        "title": str(cfg.get("web", "title", default="M2 Kiralık")),
        "unknown_walk_min": float(cfg.get("commute", "unknown_walk_min", default=10)),
        "ride_min_per_stop": float(cfg.get("commute", "ride_min_per_stop", default=2.2)),
        "items": items,
    }


def _hours_ago(h: float) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M")


def source_status(db: DB) -> dict[str, Any]:
    """Kaynak başına son deneme ve son başarılı tarama özeti (site 'Durum' sekmesi)."""
    out: dict[str, Any] = {}
    srcs = [r[0] for r in db.conn.execute("SELECT DISTINCT source FROM scan_log")]
    for src in srcs:
        last = db.conn.execute("SELECT MAX(started_at) FROM scan_log WHERE source=?", (src,)).fetchone()[0]
        row = db.conn.execute(
            "SELECT MAX(finished_at), SUM(items), SUM(pages), SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) "
            "FROM scan_log WHERE source=? AND started_at=?", (src, last)).fetchone()
        errs = [r[0] for r in db.conn.execute(
            "SELECT DISTINCT error FROM scan_log WHERE source=? AND started_at=? AND error IS NOT NULL LIMIT 3", (src, last))]
        ok = db.conn.execute("SELECT MAX(finished_at) FROM scan_log WHERE source=? AND items > 0", (src,)).fetchone()[0]
        active = db.conn.execute("SELECT COUNT(*), SUM(matches) FROM listings WHERE source=? AND active=1", (src,)).fetchone()
        out[src] = {"last": row[0], "items": int(row[1] or 0), "pages": int(row[2] or 0), "errors": int(row[3] or 0),
                    "error_texts": [e[:240] for e in errs], "last_ok": ok,
                    "active": int(active[0] or 0), "matching": int(active[1] or 0)}
    return out


def export_site(cfg: Config, db: DB, out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_payload(cfg, db)
    (out_dir / "data.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    shutil.copyfile(TEMPLATE, out_dir / "index.html")
    og = TEMPLATE.parent / "og.png"      # bağlantı önizleme görseli (WhatsApp/Telegram)
    if og.exists():
        shutil.copyfile(og, out_dir / "og.png")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return {"items": len(payload["items"]), "matching": sum(1 for i in payload["items"] if i["ok"]), "out": str(out_dir)}
