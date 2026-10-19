"""Basit zamanlayıcı: N saatte bir tarama, her gün HH:MM'de özet, /tara isteği.
Tarama ana thread'de çalışır (Playwright kısıtı)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .format import esc
from .pipeline import Pipeline

log = logging.getLogger(__name__)


def _next_daily(now: datetime, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    nxt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return nxt


def run_forever(p: Pipeline, scan_on_start: bool = True) -> None:
    tz = ZoneInfo(p.cfg.timezone)
    interval = timedelta(hours=p.cfg.scan_interval_hours)
    now = datetime.now(tz)
    next_scan = now if scan_on_start else now + interval
    next_summary = _next_daily(now, str(p.cfg.get("daily_summary_time", default="09:00")))
    log.info("zamanlayıcı: her %s saatte tarama, günlük özet %s (%s)", p.cfg.scan_interval_hours,
             next_summary.strftime("%H:%M"), p.cfg.timezone)
    while True:
        now = datetime.now(tz)
        if p.scan_requested.is_set() or now >= next_scan:
            requested = p.scan_requested.is_set()
            try:
                s = p.run_scan(trigger="telegram" if requested else "scheduled")
                if requested and not s.get("skipped"):
                    p.notifier.send(
                        f"✅ Tarama bitti: yeni {s['new']}, fiyat düşüşü {s['price_drop']}, kalkan {s['removed']}, "
                        f"bildirim {s['notified']}, hata {len(s['errors'])}"
                        + ("\n" + "\n".join("• " + esc(e) for e in s["errors"][:5]) if s["errors"] else ""),
                        subject="m2kira tarama")
            except Exception as exc:  # noqa: BLE001
                log.exception("tarama çöktü")
                try:
                    p.notifier.send(f"🛠 Tarama çöktü: {esc(exc)}", subject="m2kira hata")
                except Exception:
                    pass
            next_scan = datetime.now(tz) + interval
        if now >= next_summary:
            try:
                p.send_daily_summary()
            except Exception as exc:  # noqa: BLE001
                log.exception("özet gönderilemedi: %s", exc)
            next_summary = _next_daily(datetime.now(tz), str(p.cfg.get("daily_summary_time", default="09:00")))
        time.sleep(5)
