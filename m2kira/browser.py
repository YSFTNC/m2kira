"""Playwright (headless Chromium) ile sayfa getirme. Cloudflare 'Just a moment' bekleme,
kalıcı profil (çerez/oturum), istek aralığı ve disk önbelleği. Bu nesne yalnızca
oluşturulduğu thread'den kullanılmalıdır (Playwright sync API kısıtı)."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .http import DEFAULT_UA, BlockedError, DiskCache, RateLimiter, SourceError

log = logging.getLogger(__name__)


@dataclass
class BrowserPage:
    url: str
    status: int
    title: str
    html: str
    final_url: str
    state: Optional[dict] = None     # window.__NUXT__ gibi JSON durum
    from_cache: bool = False


def display_available() -> bool:
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


class BrowserFetcher:
    def __init__(self, profile_dir: Path, cache_dir: Path, min_interval: float = 5.0,
                 headless: bool = True, user_agent: str = DEFAULT_UA, challenge_wait: float = 45.0,
                 cooldown: float = 120.0, block_resources: bool = False, offscreen: bool = False,
                 cdp_url: Optional[str] = None):
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        # cdp_url verilirse kendi Chromium'u açmak yerine kullanıcının çalışan Chrome'una bağlanır
        # (chrome.exe --remote-debugging-port=9222). Bot korumasını kullanıcı kendi tarayıcısında geçer.
        self.cdp_url = cdp_url
        self._browser = None
        self.cache = DiskCache(cache_dir)
        self.limiter = RateLimiter(min_interval)
        self.headless = headless
        self.offscreen = offscreen   # görünür modda pencereyi ekran dışına koy (taramada rahatsız etmesin)
        self.user_agent = user_agent
        self.challenge_wait = challenge_wait
        self.cooldown = cooldown   # 429 / çözülemeyen doğrulama sonrası bekleyip bir kez daha dene
        # Sayfa başına yalnızca ana dokümanı (ve Cloudflare doğrulama kaynaklarını) yükle: resim/JS/XHR
        # trafiği Cloudflare hız sınırına sayılıyor; SSR HTML + inline __NUXT__ bize yetiyor.
        self.block_resources = block_resources
        self.stats = {"navigations": 0, "blocked_requests": 0}
        self._pw = None
        self._ctx = None
        self._page = None

    # ------------------------------------------------------------------ yaşam döngüsü
    def _ensure(self):
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise SourceError("playwright kurulu değil: pip install playwright && python -m playwright install chromium") from exc
        self._pw = sync_playwright().start()
        if self.cdp_url:
            try:
                self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url, timeout=10000)
            except Exception as exc:
                self._pw.stop()
                self._pw = None
                raise SourceError(f"Chrome'a bağlanılamadı ({self.cdp_url}). Chrome'u uzaktan hata ayıklama "
                                  f"portuyla başlatın: python main.py sahibinden-chrome  ({exc})") from exc
            self._ctx = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
            self._page = self._ctx.new_page()
            self._page.set_default_timeout(60000)
            return
        args = ["--disable-blink-features=AutomationControlled"]
        if not self.headless and self.offscreen:
            args.append("--window-position=-32000,0")
        # M2KIRA_BROWSER_CHANNEL=chrome -> sistemdeki Google Chrome (GitHub Actions'ta hazır kurulu);
        # açılamazsa Playwright'ın kendi Chromium'una düşülür.
        channels = [os.environ.get("M2KIRA_BROWSER_CHANNEL") or None]
        if channels[0]:
            channels.append(None)
        last_exc: Optional[Exception] = None
        for channel in channels:
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(
                    str(self.profile_dir),
                    channel=channel,
                    headless=self.headless,
                    user_agent=self.user_agent,
                    locale="tr-TR",
                    timezone_id="Europe/Istanbul",
                    viewport={"width": 1366, "height": 850},
                    args=args,
                )
                break
            except Exception as exc:
                last_exc = exc
                log.warning("tarayıcı (%s) açılamadı: %s", channel or "chromium", str(exc).splitlines()[0][:200])
        if self._ctx is None:
            self._pw.stop()
            self._pw = None
            raise SourceError(f"Chromium başlatılamadı: {last_exc}") from last_exc
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._page.set_default_timeout(60000)
        if self.block_resources:
            self._page.route("**/*", self._route)

    _ALLOW_SUBSTR = ("/cdn-cgi/", "challenges.cloudflare.com", "cloudflareinsights")

    def _route(self, route, request) -> None:
        try:
            if request.resource_type == "document" or any(s in request.url for s in self._ALLOW_SUBSTR):
                route.continue_()
            else:
                self.stats["blocked_requests"] += 1
                route.abort()
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    def restart(self, headless: Optional[bool] = None, offscreen: Optional[bool] = None) -> None:
        self.close()
        if headless is not None:
            self.headless = headless
        if offscreen is not None:
            self.offscreen = offscreen
        self._ensure()

    def close(self) -> None:
        if self.cdp_url:
            # kullanıcının Chrome'unu kapatma; yalnızca açtığımız sekmeyi kapat ve bağlantıyı kes
            closers = (lambda: self._page.close() if self._page else None,
                       lambda: self._browser.close() if self._browser else None,
                       lambda: self._pw.stop() if self._pw else None)
        else:
            closers = (lambda: self._ctx.close() if self._ctx else None,
                       lambda: self._pw.stop() if self._pw else None)
        for closer in closers:
            try:
                closer()
            except Exception:
                pass
        self._pw = self._ctx = self._page = self._browser = None

    @property
    def page(self):
        self._ensure()
        return self._page

    # ------------------------------------------------------------------ getirme
    def get(self, url: str, ttl: float = 0, state_expr: Optional[str] = None,
            wait_selector: Optional[str] = None) -> BrowserPage:
        cached = self.cache.get(url, ttl)
        if cached:
            return BrowserPage(url=url, status=int(cached["status"]), title=cached.get("title", ""),
                               html=cached["text"], final_url=cached.get("final_url", url),
                               state=cached.get("state"), from_cache=True)
        self._ensure()
        host = urlparse(url).netloc
        page = self._page
        status = 0
        title = ""
        for attempt in range(2):
            self.limiter.wait(host)
            try:
                resp = page.goto(url, wait_until="domcontentloaded")
                self.stats["navigations"] += 1
            except Exception as exc:
                raise SourceError(f"{url} yüklenemedi: {exc}") from exc
            status = resp.status if resp else 0
            deadline = time.time() + self.challenge_wait
            title = page.title()
            while time.time() < deadline and _is_challenge(title):
                time.sleep(2.0)
                title = page.title()
            if not _is_challenge(title):
                if status in (403, 429, 503):
                    status = 200  # doğrulama geçildi, gerçek sayfa yüklendi
                break
            if attempt == 0 and self.cooldown > 0:
                log.warning("%s: doğrulama/hız sınırı (HTTP %s, %r); %.0f sn bekleyip yeniden denenecek",
                            host, status, title, self.cooldown)
                time.sleep(self.cooldown)
                continue
            raise BlockedError(f"{host}: Cloudflare doğrulaması geçilemedi (HTTP {status}, {title!r})")
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=15000)
            except Exception:
                pass
        state = None
        if state_expr:
            try:
                raw = page.evaluate(f"() => JSON.stringify({state_expr} || null)")
                state = json.loads(raw) if raw else None
            except Exception as exc:
                log.debug("state alınamadı: %s", exc)
        html = page.content()
        out = BrowserPage(url=url, status=status, title=title, html=html, final_url=page.url, state=state)
        if status == 200 and ttl > 0 and (state is not None or not state_expr):
            self.cache.put(url, {"status": status, "text": html, "title": title, "final_url": page.url, "state": state})
        return out


def _is_challenge(title: str) -> bool:
    t = (title or "").lower()
    return ("just a moment" in t or "bir dakika" in t or "attention required" in t
            or "doğrulama" in t or "dogrulama" in t)
