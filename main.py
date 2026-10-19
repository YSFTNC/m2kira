"""m2kira komut satırı.

  python main.py run                # zamanlayıcı + Telegram botu (sürekli çalışır)
  python main.py scan               # tek tarama, bildirim gönderir
  python main.py scan --dry         # tek tarama, bildirim yerine konsola yazar
  python main.py summary            # özeti gönder
  python main.py list [--all]       # uygun ilanları yazdır
  python main.py status
  python main.py check-known        # handoff'taki bilinen ilanlar veritabanında mı?
  python main.py sahibinden-login   # sahibinden için bir kerelik tarayıcı girişi
  python main.py test-notify        # bildirim kanalını dene
"""
from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from m2kira.config import load_config
from m2kira.db import DB
from m2kira.format import fmt_price, format_line
from m2kira.notify import ConsoleNotifier, MultiNotifier, TelegramNotifier, build_notifier
from m2kira.notify.base import strip_html
from m2kira.pipeline import Pipeline


def setup_logging(data_dir: Path, verbose: bool) -> None:
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(RotatingFileHandler(data_dir / "m2kira.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format=fmt, handlers=handlers)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(description="Ankara M2 eşyalı kiralık ilan takipçisi")
    ap.add_argument("-c", "--config", default=None, help="config.yaml yolu")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--dry", action="store_true", help="bildirim gönderme, konsola yaz")
    p_scan.add_argument("--source", default=None, help="yalnızca bu kaynak (hepsiemlak|emlakjet|sahibinden)")
    p_scan.add_argument("--neighborhood", default=None, help="yalnızca bu mahalle")
    sub.add_parser("summary")
    p_list = sub.add_parser("list")
    p_list.add_argument("--all", action="store_true", help="bütçe üstü (pazarlıkla) dahil")
    sub.add_parser("status")
    sub.add_parser("check-known")
    sub.add_parser("sahibinden-login")
    sub.add_parser("sahibinden-chrome", help="gerçek Chrome'u ayrı profil + uzaktan hata ayıklama portuyla aç (cdp modu)")
    sub.add_parser("test-notify")
    sub.add_parser("bot-once", help="birikmiş Telegram komutlarını bir kez işle (cron / GitHub Actions)")
    p_web = sub.add_parser("export-web", help="filtre sayfasını (index.html + data.json) üret")
    p_web.add_argument("--out", default="_site")
    p_feed = sub.add_parser("feed-push", help="PC: hepsiemlak'ı tara, GitHub'a besleme olarak gönder, işi tetikle")
    p_feed.add_argument("--no-push", action="store_true", help="yalnız tara, data/feed/hepsiemlak.json'a yaz")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    setup_logging(cfg.data_dir, args.verbose)
    log = logging.getLogger("main")
    db = DB(cfg.db_path)

    if args.cmd == "sahibinden-login":
        from m2kira.sources.sahibinden import SahibindenSource
        src = SahibindenSource(cfg)
        ok = src.interactive_login()
        print("Giriş kaydedildi." if ok else "Giriş algılanamadı (süre doldu veya pencere kapatıldı).")
        return 0 if ok else 1

    if args.cmd == "sahibinden-chrome":
        from m2kira.sources.sahibinden import SahibindenSource
        src = SahibindenSource(cfg)
        exe = src.launch_user_chrome()
        if not exe:
            print("Google Chrome bulunamadı. Elle başlatın:\n"
                  f'  chrome.exe --remote-debugging-port=9222 --user-data-dir="{cfg.data_dir / "chrome-profile"}" https://secure.sahibinden.com/giris')
            return 1
        print(f"Chrome açıldı ({exe}). Bu pencerede doğrulamayı geçip sahibinden'e giriş yapın; pencereyi açık bırakın.\n"
              "config.yaml -> sources.sahibinden.mode: cdp olmalı. Deneme: python main.py scan --dry --source sahibinden --neighborhood Kızılay")
        return 0

    if args.cmd == "feed-push":
        import json as _json
        from m2kira import feed
        feed.sync_budget_from_web(cfg, db)
        payload = feed.collect(cfg, db)
        out = cfg.data_dir / "feed" / "hepsiemlak.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        log.info("hepsiemlak beslemesi: %d birim, %d ilan, %d hata -> %s", len(payload["units"]), payload["listings"],
                 len(payload["errors"]), out)
        rc = 0
        if not payload["units"]:
            log.warning("hiç birim taranamadı; gönderilmiyor (%s)", "; ".join(payload["errors"])[:300])
            rc = 1
        elif not args.no_push:
            try:
                where = feed.push(cfg, payload)
                log.info("besleme gönderildi: %s", where)
                if feed.trigger(cfg):
                    log.info("GitHub işi tetiklendi (hepsiemlak_feed)")
            except Exception as exc:  # noqa: BLE001
                log.error("besleme gönderilemedi: %s", exc)
                rc = 1
        db.close()
        return rc

    if args.cmd == "export-web":
        from m2kira.web import export_site
        info = export_site(cfg, db, Path(args.out))
        print(f"filtre sayfası: {info['items']} aktif ilan ({info['matching']} uygun) -> {info['out']}")
        db.close()
        return 0

    notifier = build_notifier(cfg)
    if args.cmd == "test-notify":
        ok = notifier.send("✅ m2kira bildirim testi — bu mesajı görüyorsanız kanal çalışıyor.", subject="m2kira test")
        print("gönderildi" if ok else "gönderilemedi (log'a bakın)")
        return 0 if ok else 1

    if args.cmd == "scan" and args.dry:
        notifier = ConsoleNotifier()

    sources = None
    if args.cmd == "scan" and (args.source or args.neighborhood):
        from m2kira.sources import build_sources
        sources = [s for s in build_sources(cfg) if not args.source or s.name == args.source]
        if args.neighborhood:
            nb = cfg.neighborhood_by_key(args.neighborhood)
            if not nb:
                print(f"mahalle bulunamadı: {args.neighborhood}")
                return 2
            cfg.neighborhoods = [nb]
    p = Pipeline(cfg, db, notifier, sources=sources)
    try:
        if args.cmd == "run":
            from m2kira.scheduler import run_forever
            tg = None
            if isinstance(notifier, TelegramNotifier):
                tg = notifier
            elif isinstance(notifier, MultiNotifier):
                tg = next((n for n in notifier.notifiers if isinstance(n, TelegramNotifier)), None)
            if tg:
                from m2kira.bot import TelegramBot
                TelegramBot(p, tg).start()
            else:
                log.warning("Telegram kanalı yok; komutlar devre dışı, yalnızca zamanlayıcı çalışıyor")
            run_forever(p, scan_on_start=bool(cfg.get("scan_on_start", default=True)))
        elif args.cmd == "scan":
            s = p.run_scan(trigger="cli")
            print(f"yeni={s.get('new')} fiyat_dusus={s.get('price_drop')} kalkan={s.get('removed')} "
                  f"bildirim={s.get('notified')} hata={len(s.get('errors', []))}")
            for e in s.get("errors", []):
                print("  !", e)
            for name, st in s.get("sources", {}).items():
                print(f"  {name}: {st}")
        elif args.cmd == "summary":
            p.send_daily_summary()
        elif args.cmd == "bot-once":
            tg = notifier if isinstance(notifier, TelegramNotifier) else (
                next((n for n in notifier.notifiers if isinstance(n, TelegramNotifier)), None) if isinstance(notifier, MultiNotifier) else None)
            if not tg:
                print("Telegram kanalı yok.")
                return 2
            from m2kira.bot import TelegramBot
            n = TelegramBot(p, tg).poll_once()
            print(f"{n} komut işlendi")
        elif args.cmd == "list":
            rows = p.matching_listings(max_price=None if args.all else p.budget())
            print(f"{len(rows)} ilan (bütçe {fmt_price(p.budget())})")
            for r in rows:
                print(strip_html(format_line(r)))
        elif args.cmd == "status":
            print(strip_html(p.status_text()))
        elif args.cmd == "check-known":
            from m2kira.known import KNOWN_ACTIVE, KNOWN_GONE
            found = 0
            for lid, info in KNOWN_ACTIVE.items():
                row = db.get(lid)
                if row:
                    found += 1
                    exp = info.get("price")
                    mark = "" if not exp or exp == row.get("price") else f"  (beklenen {exp})"
                    print(f"OK   {lid:28} {fmt_price(row.get('price')):>12} {row.get('rooms') or '?':5} "
                          f"{(row.get('district') or '?'):18} furnished={row.get('furnished')} flags={row.get('flags')}{mark}")
                else:
                    print(f"YOK  {lid:28} {info.get('note', '')}")
            print(f"{found}/{len(KNOWN_ACTIVE)} bilinen ilan veritabanında")
            for lid in KNOWN_GONE:
                row = db.get(lid)
                print(f"{'aktif!' if row and row.get('active') else 'yok/pasif':10} {lid} (kalkmış olmalı)")
    finally:
        p.close()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
