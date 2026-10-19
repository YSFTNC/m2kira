"""Kibar HTTP getirici: istek aralığı, disk önbelleği, gerçekçi User-Agent, yeniden deneme."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


class SourceError(Exception):
    """Kaynakla ilgili genel hata."""


class BlockedError(SourceError):
    """Bot koruması / 403 — bu kaynak şimdilik erişilemez."""


class LoginRequiredError(SourceError):
    """Site giriş (oturum) istiyor."""


class ParseError(SourceError):
    """Sayfa geldi ama beklenen veri bulunamadı (site değişmiş olabilir)."""


@dataclass
class Response:
    url: str
    status: int
    text: str
    from_cache: bool = False
    final_url: Optional[str] = None


class RateLimiter:
    """Host başına en az `min_interval` saniye aralık. Thread-güvenli."""

    def __init__(self, min_interval: float = 5.0):
        self.min_interval = float(min_interval)
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            last = self._last.get(host, 0.0)
            delay = self.min_interval - (now - last)
            if delay > 0:
                time.sleep(delay)
            self._last[host] = time.monotonic()


class DiskCache:
    def __init__(self, cache_dir: Path):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")

    def get(self, key: str, ttl: float) -> Optional[dict]:
        p = self._path(key)
        if ttl <= 0 or not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        if time.time() - float(data.get("fetched_at", 0)) > ttl:
            return None
        return data

    def put(self, key: str, payload: dict) -> None:
        payload = dict(payload)
        payload["fetched_at"] = time.time()
        try:
            self._path(key).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # önbellek yazılamazsa sorun değil
            log.debug("cache write failed: %s", exc)


class Fetcher:
    def __init__(self, cache_dir: Path, min_interval: float = 5.0, user_agent: str = DEFAULT_UA,
                 timeout: float = 40.0, retries: int = 3):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
        })
        self.limiter = RateLimiter(min_interval)
        self.cache = DiskCache(cache_dir)
        self.timeout = timeout
        self.retries = retries

    def get(self, url: str, ttl: float = 0, allow_404: bool = False) -> Response:
        cached = self.cache.get(url, ttl)
        if cached:
            return Response(url=url, status=int(cached["status"]), text=cached["text"], from_cache=True,
                            final_url=cached.get("final_url"))
        host = urlparse(url).netloc
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries):
            self.limiter.wait(host)
            try:
                r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            except requests.RequestException as exc:
                last_exc = exc
                log.warning("GET %s başarısız (%s), deneme %d", url, exc, attempt + 1)
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code in (403, 429, 503) and ("Just a moment" in r.text or r.status_code == 403):
                raise BlockedError(f"{host} erişimi engelledi (HTTP {r.status_code})")
            if r.status_code >= 500 or r.status_code == 429:
                last_exc = SourceError(f"HTTP {r.status_code}")
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 404 and not allow_404:
                raise SourceError(f"HTTP 404: {url}")
            resp = Response(url=url, status=r.status_code, text=r.text, final_url=r.url)
            if r.status_code == 200 and ttl > 0:
                self.cache.put(url, {"status": r.status_code, "text": r.text, "final_url": r.url})
            return resp
        raise SourceError(f"{url} alınamadı: {last_exc}")
