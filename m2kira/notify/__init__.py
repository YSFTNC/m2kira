"""Bildirim kanalları: telegram | email | ntfy | console (birden fazlası seçilebilir)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import ConsoleNotifier, MultiNotifier, Notifier
from .email import EmailNotifier
from .ntfy import NtfyNotifier
from .telegram import TelegramNotifier

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Config

log = logging.getLogger(__name__)

__all__ = ["Notifier", "ConsoleNotifier", "MultiNotifier", "EmailNotifier", "NtfyNotifier",
           "TelegramNotifier", "build_notifier"]


def build_notifier(cfg: "Config") -> Notifier:
    channels = cfg.get("notify", "channels", default=None) or [cfg.get("notify", "channel", default="console")]
    out: list[Notifier] = []
    for ch in channels:
        ch = str(ch).lower()
        if ch == "telegram":
            token = cfg.secret("TELEGRAM_BOT_TOKEN")
            chat = cfg.secret("TELEGRAM_CHAT_ID")
            if not token:
                log.warning("TELEGRAM_BOT_TOKEN yok; telegram kanalı atlandı")
                continue
            out.append(TelegramNotifier(token=token, chat_id=chat))
        elif ch == "email":
            out.append(EmailNotifier(
                host=cfg.secret("SMTP_HOST", cfg.get("notify", "email", "host", default="")) or "",
                port=int(cfg.secret("SMTP_PORT", str(cfg.get("notify", "email", "port", default=587))) or 587),
                user=cfg.secret("SMTP_USER", "") or "",
                password=cfg.secret("SMTP_PASSWORD", "") or "",
                sender=cfg.secret("EMAIL_FROM", cfg.get("notify", "email", "from", default="")) or "",
                recipient=cfg.secret("EMAIL_TO", cfg.get("notify", "email", "to", default="")) or "",
                use_tls=bool(cfg.get("notify", "email", "tls", default=True)),
            ))
        elif ch == "ntfy":
            out.append(NtfyNotifier(
                topic=cfg.secret("NTFY_TOPIC", cfg.get("notify", "ntfy", "topic", default="")) or "",
                server=cfg.secret("NTFY_SERVER", cfg.get("notify", "ntfy", "server", default="https://ntfy.sh")) or "https://ntfy.sh",
            ))
        elif ch == "console":
            out.append(ConsoleNotifier())
        else:
            log.warning("bilinmeyen bildirim kanalı: %s", ch)
    if not out:
        out.append(ConsoleNotifier())
    return out[0] if len(out) == 1 else MultiNotifier(out)
