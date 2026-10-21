"""Web sitesinden kaydedilen ayarlar (feed dalındaki feed/settings.json).

Site, kullanıcının GitHub anahtarıyla bu dosyayı yazar; GitHub Actions her çalıştırmada indirip uygular.
  * Her çalıştırmada (config üzerine): tolerans, oda, eşya, yürüme, hariç bayraklar, bildirim durakları,
    kalkma bildirimi, favoriler.
  * Dosya her güncellendiğinde bir kez (veritabanına): bütçe, gizle/göster, kapalı mahalleler.
    (Telegram'dan /butce, /gizle, /mahalle ile yapılan değişiklikler site yeniden kaydedene kadar geçerli kalır.)
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .db import DB
from .textnorm import fold

log = logging.getLogger(__name__)

CONFIG_KEYS = ("budget_tolerance_pct", "rooms_allowed", "furnished_accept", "include_unknown_furnished",
               "max_walk_m", "walk_tolerance_m", "exclude_flags", "notify_removed", "notify_stations",
               "notify_all_changes")
VALID_FURNISHED = {"full", "partial", "either", "unknown", "none"}
VALID_ROOMS = {"1+0", "1+1", "2+1", "3+1", "4+1", "5+1"}


def settings_path(cfg: Config) -> Path:
    return Path(os.environ.get("M2KIRA_SETTINGS_FILE") or (cfg.data_dir / "feed" / "settings.json"))


def load(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        log.warning("site ayarları okunamadı: %s", exc)
        return None


def _clean(s: dict[str, Any]) -> dict[str, Any]:
    """Siteden gelen değerleri doğrula; geçersizleri at (public repo: dosyayı yalnız anahtar sahibi yazar
    ama yine de tip/aralık kontrolü yapılır)."""
    out: dict[str, Any] = {}

    def num(k, lo, hi):
        v = s.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi:
            out[k] = v

    num("budget", 1000, 500000)
    num("budget_tolerance_pct", 0, 50)
    num("max_walk_m", 200, 5000)
    num("walk_tolerance_m", 0, 3000)
    if isinstance(s.get("rooms_allowed"), list):
        out["rooms_allowed"] = [r for r in s["rooms_allowed"] if r in VALID_ROOMS]
    if isinstance(s.get("furnished_accept"), list):
        fa = [f for f in s["furnished_accept"] if f in VALID_FURNISHED]
        if fa:
            out["furnished_accept"] = fa
    for k in ("include_unknown_furnished", "notify_removed", "notify_all_changes"):
        if isinstance(s.get(k), bool):
            out[k] = s[k]
    for k in ("exclude_flags", "notify_stations", "disabled_neighborhoods", "favorites"):
        if isinstance(s.get(k), list):
            out[k] = [str(x)[:80] for x in s[k] if isinstance(x, (str, int))][:2000]
    if isinstance(s.get("hidden"), dict):
        out["hidden"] = {str(k)[:80]: bool(v) for k, v in list(s["hidden"].items())[:5000]}
    if isinstance(s.get("updated"), str):
        out["updated"] = s["updated"][:40]
    return out


def apply(cfg: Config, db: DB, raw: Optional[dict[str, Any]]) -> list[str]:
    """Ayarları uygular; yapılan değişikliklerin kısa listesini döndürür."""
    if not raw:
        return []
    s = _clean(raw)
    changes: list[str] = []
    for k in CONFIG_KEYS:
        if k in s:
            cfg.raw[k] = s[k]
    cfg.raw["favorites"] = s.get("favorites", [])
    updated = s.get("updated")
    if updated and db.get_setting("site_settings_applied") != updated:
        if "budget" in s and int(db.get_setting("budget", cfg.budget)) != int(s["budget"]):
            db.set_setting("budget", int(s["budget"]))
            changes.append(f"bütçe {int(s['budget'])}")
        for lid, hidden in (s.get("hidden") or {}).items():
            if db.get(lid):
                db.set_hidden(lid, hidden)
        if "hidden" in s:
            changes.append(f"gizle/göster {len(s['hidden'])}")
        if "disabled_neighborhoods" in s:
            db.set_setting("disabled_neighborhoods", sorted({fold(n) for n in s["disabled_neighborhoods"]}))
            changes.append(f"kapalı mahalle {len(s['disabled_neighborhoods'])}")
        db.set_setting("site_settings_applied", updated)
        db.set_setting("site_settings_updated", updated)
        log.info("site ayarları uygulandı (%s): %s", updated, ", ".join(changes) or "yalnız filtreler")
    return changes


def apply_from_file(cfg: Config, db: DB) -> list[str]:
    return apply(cfg, db, load(settings_path(cfg)))


def effective(cfg: Config, db: DB) -> dict[str, Any]:
    """Sitenin ayar formunu dolduracak geçerli değerler."""
    return {
        "budget": int(db.get_setting("budget", cfg.budget)),
        "budget_tolerance_pct": cfg.budget_tolerance_pct,
        "rooms_allowed": list(cfg.get("rooms_allowed", default=[]) or []),
        "furnished_accept": list(cfg.get("furnished_accept", default=["full", "partial", "either"]) or []),
        "include_unknown_furnished": bool(cfg.get("include_unknown_furnished", default=False)),
        "max_walk_m": int(cfg.get("max_walk_m", default=1000)),
        "walk_tolerance_m": int(cfg.get("walk_tolerance_m", default=500)),
        "exclude_flags": list(cfg.get("exclude_flags", default=["gunluk", "oda", "uzak"]) or []),
        "notify_removed": bool(cfg.get("notify_removed", default=True)),
        "notify_all_changes": bool(cfg.get("notify_all_changes", default=True)),
        "notify_stations": list(cfg.get("notify_stations", default=[]) or []),
        "disabled_neighborhoods": list(db.get_setting("disabled_neighborhoods", []) or []),
        "favorites": list(cfg.get("favorites", default=[]) or []),
        "updated": db.get_setting("site_settings_updated"),
    }
