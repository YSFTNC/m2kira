from __future__ import annotations

import logging

import requests

from .base import Notifier, strip_html

log = logging.getLogger(__name__)


class NtfyNotifier(Notifier):
    name = "ntfy"

    def __init__(self, topic: str, server: str = "https://ntfy.sh"):
        self.topic = topic
        self.server = server.rstrip("/")

    def send(self, text: str, subject: str = "m2kira") -> bool:
        if not self.topic:
            log.warning("NTFY_TOPIC yok; ntfy atlandı")
            return False
        r = requests.post(f"{self.server}/{self.topic}", data=strip_html(text).encode("utf-8"),
                          headers={"Title": subject.encode("ascii", "ignore").decode(), "Markdown": "no"}, timeout=30)
        return r.ok
