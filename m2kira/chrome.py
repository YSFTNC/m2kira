"""Kullanıcının gerçek Google Chrome'unu ayrı profil (data/chrome-profile) + uzaktan hata ayıklama portuyla
başlatır. sahibinden yalnızca gerçek Chrome + giriş yapılmış oturumla arama sonucu gösteriyor.

19.10.2026 testi: `--headless=new` + normal kullanıcı ajanı + kayıtlı profil -> bot korumasını geçti
(navigator.webdriver=false, 72 sonuç). Böylece PC görevi ekranda pencere açmadan çalışır.

    with ChromeSession(profile_dir, port=9222, headless=True):
        ... SahibindenSource(mode=cdp) ile tara ...

Port zaten açıksa (kullanıcı `python main.py sahibinden-chrome` ile görünür Chrome açmışsa) o kullanılır ve
kapatılmaz.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Optional

from .http import SourceError

log = logging.getLogger(__name__)

CHROME_CANDIDATES = [
    os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Google", "Chrome", "Application", "chrome.exe"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), "Google", "Chrome", "Application", "chrome.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chrome() -> Optional[str]:
    return next((c for c in CHROME_CANDIDATES if c and os.path.exists(c)), None)


def chrome_major(exe: str) -> Optional[str]:
    """Kurulu Chrome sürümü (Application\\<sürüm> klasöründen)."""
    try:
        app = Path(exe).parent
        vers = [d.name for d in app.iterdir() if d.is_dir() and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", d.name)]
        if vers:
            return max(vers, key=lambda v: tuple(int(x) for x in v.split("."))).split(".")[0]
    except Exception:
        pass
    return None


def endpoint_up(port: int) -> Optional[dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
            return json.load(r)
    except Exception:
        return None


class ChromeSession:
    def __init__(self, profile_dir: Path, port: int = 9222, headless: bool = True, start_url: str = "about:blank"):
        self.profile_dir = Path(profile_dir)
        self.port = port
        self.headless = headless
        self.start_url = start_url
        self.proc: Optional[subprocess.Popen] = None
        self.launched = False

    @property
    def cdp_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "ChromeSession":
        if endpoint_up(self.port):
            log.info("Chrome zaten açık (port %d), o kullanılacak", self.port)
            return self
        exe = find_chrome()
        if not exe:
            raise SourceError("Google Chrome bulunamadı")
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        args = [exe, f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile_dir}",
                "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                "--window-size=1366,900"]
        if self.headless:
            major = chrome_major(exe) or "155"
            ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
            args += ["--headless=new", f"--user-agent={ua}"]
        else:
            args += ["--window-position=-32000,-32000"]
        args.append(self.start_url)
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.launched = True
        for _ in range(40):
            time.sleep(0.5)
            if endpoint_up(self.port):
                return self
        self.__exit__(None, None, None)
        raise SourceError("Chrome başlatıldı ama hata ayıklama portu açılmadı")

    def __exit__(self, *exc) -> None:
        if not self.launched:
            return
        # nazik kapanış: çerezler/oturum diske yazılsın
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.connect_over_cdp(self.cdp_url, timeout=5000)
                try:
                    b.new_browser_cdp_session().send("Browser.close")
                except Exception:
                    pass
        except Exception:
            pass
        if self.proc is not None:
            try:
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.terminate()
        self.launched = False
