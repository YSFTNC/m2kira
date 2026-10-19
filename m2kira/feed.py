"""PC -> GitHub besleme: hepsiemlak yalnızca ev internetinden (Cloudflare) erişilebildiği için PC açıkken
taranır, sonuç reponun `feed` dalına JSON olarak yazılır ve GitHub Actions işi tetiklenir. GitHub tarafında
`hepsiemlak_feed` kaynağı bu dosyayı okur; bildirim/kopya/filtre sayfası tek yerden yönetilir.

    python main.py feed-push            # tara + gönder + GitHub işini tetikle (Görev Zamanlayıcı bunu çalıştırır)
    python main.py feed-push --no-push  # yalnız tara, data/feed/hepsiemlak.json'a yaz
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from .config import Config
from .db import DB
from .http import BlockedError, LoginRequiredError
from .models import Listing

log = logging.getLogger(__name__)
FEED_SOURCE = "hepsiemlak"
DROP_FIELDS = {"matches", "match_tier", "flags", "nearest_station", "distance_m", "walk_minutes_est",
               "distance_verified", "furnished", "price_includes", "scan_key"}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def feed_cfg(cfg: Config) -> dict[str, Any]:
    d = dict(cfg.source_cfg("hepsiemlak_feed"))
    d.setdefault("repo", "YSFTNC/m2kira")
    d.setdefault("branch", "feed")
    d.setdefault("path", "feed/hepsiemlak.json")
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
    """GitHub'daki güncel bütçeyi (/butce ile değişmiş olabilir) yayınlanan data.json'dan al."""
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


def collect(cfg: Config, db: DB) -> dict[str, Any]:
    """hepsiemlak'ı (hızlı/tam geçiş planıyla) tarar, besleme sözlüğü döndürür."""
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
    return {"generated": utcnow(), "source": FEED_SOURCE, "units": units, "errors": errors,
            "listings": sum(len(u["listings"]) for u in units)}


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
    fc = feed_cfg(cfg)
    repo, branch, path = fc["repo"], fc["branch"], fc["path"]
    # dal yoksa main'den oluştur
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
        "message": f"hepsiemlak beslemesi {payload['generated']} ({payload['listings']} ilan)",
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


def trigger(cfg: Config) -> bool:
    fc = feed_cfg(cfg)
    r = _gh(["workflow", "run", "scan.yml", "--repo", fc["repo"], "-f", "sources=hepsiemlak_feed"])
    if r.returncode != 0:
        log.warning("GitHub işi tetiklenemedi: %s", r.stderr.strip()[:200])
    return r.returncode == 0
