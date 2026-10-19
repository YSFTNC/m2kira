"""Geçici deneme: GitHub sunucusundan hepsiemlak / sahibinden / emlakjet erişimi, WARP ile ve WARP'sız."""
import os, sys, time
from playwright.sync_api import sync_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
TESTS = [
    ("hepsiemlak", "https://www.hepsiemlak.com/cankaya-kizilay-mah-kiralik/daire"),
    ("sahibinden", "https://www.sahibinden.com/kiralik-daire/ankara-cankaya"),
    ("emlakjet", "https://www.emlakjet.com/kiralik-daire/ankara-cankaya-bahcelievler-mahallesi"),
]
WAIT = ("Just a moment", "Bir dakika", "Attention Required", "Lütfen bekleyin")


def run(label, proxy=None, headless=True, channel="chrome"):
    with sync_playwright() as p:
        kw = dict(headless=headless, channel=channel, args=["--disable-blink-features=AutomationControlled"])
        if proxy:
            kw["proxy"] = {"server": proxy}
        b = p.chromium.launch(**kw)
        ctx = b.new_context(locale="tr-TR", user_agent=UA, viewport={"width": 1366, "height": 900})
        for name, url in TESTS:
            page = ctx.new_page()
            t0 = time.time()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                while time.time() - t0 < 40 and any(k in page.title() for k in WAIT):
                    time.sleep(1.5)
                time.sleep(2)
                html = page.content()
                nuxt = page.evaluate("() => !!(window.__NUXT__ && window.__NUXT__.state)")
                print(f"{label:24} {name:10} {time.time() - t0:4.0f}s title={page.title()[:45]!r} url={page.url[:60]} "
                      f"len={len(html)} nuxt={nuxt} sbrows={html.count('searchResultsItem')}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"{label:24} {name:10} ERROR {str(e)[:120]}", flush=True)
            page.close()
            time.sleep(3)
        b.close()


mode = sys.argv[1]
if mode == "direct":
    run("direct headless")
elif mode == "warp":
    run("warp headless", proxy="socks5://127.0.0.1:40000")
elif mode == "warp-headed":
    run("warp headed(xvfb)", proxy="socks5://127.0.0.1:40000", headless=False)
