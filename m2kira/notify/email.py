from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .base import Notifier, strip_html

log = logging.getLogger(__name__)


class EmailNotifier(Notifier):
    name = "email"

    def __init__(self, host: str, port: int, user: str, password: str, sender: str, recipient: str, use_tls: bool = True):
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sender, self.recipient, self.use_tls = sender or user, recipient, use_tls

    def send(self, text: str, subject: str = "m2kira") -> bool:
        if not (self.host and self.recipient):
            log.warning("SMTP ayarları eksik; e-posta atlandı")
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg.set_content(strip_html(text))
        msg.add_alternative(f"<html><body style='font-family:sans-serif;white-space:pre-wrap'>{text}</body></html>", subtype="html")
        with smtplib.SMTP(self.host, self.port, timeout=30) as s:
            if self.use_tls:
                s.starttls()
            if self.user:
                s.login(self.user, self.password)
            s.send_message(msg)
        return True
