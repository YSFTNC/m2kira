"""Telegram Bot API (yalnızca requests; ek kütüphane yok)."""
from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from ..format import split_message
from .base import Notifier, strip_html

log = logging.getLogger(__name__)


class TelegramNotifier(Notifier):
    name = "telegram"

    # yalnız sahibine gidecek teknik mesajlar (parser/erişim uyarıları, test)
    OWNER_ONLY_SUBJECTS = ("m2kira uyarı", "m2kira test")

    def __init__(self, token: str, chat_id: Optional[str] = None, timeout: float = 30.0):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout
        self.api = f"https://api.telegram.org/bot{token}"
        self.extra_chats: list[str] = []   # /davet ile katılan üyeler (bot veritabanından)

    def _targets(self, subject: str, chat_id: Optional[str]) -> list[str]:
        if chat_id:
            return [str(chat_id)]
        out = [str(self.chat_id)] if self.chat_id else []
        if subject not in self.OWNER_ONLY_SUBJECTS:
            out += [str(c) for c in self.extra_chats if str(c) not in out]
        return out

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        r = requests.post(f"{self.api}/{method}", json=params, timeout=self.timeout)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram {method}: {data.get('description')}")
        return data["result"]

    def send(self, text: str, subject: str = "m2kira", chat_id: Optional[str] = None) -> bool:
        targets = self._targets(subject, chat_id)
        if not targets:
            log.warning("TELEGRAM_CHAT_ID yok; bota /start yazın (chat id kaydedilir). Mesaj:\n%s", strip_html(text))
            return False
        results = [self._send_one(chat, text) for chat in targets]
        return results[0]

    def _send_one(self, chat: str, text: str) -> bool:
        ok = True
        for chunk in split_message(text):
            try:
                self.call("sendMessage", chat_id=chat, text=chunk, parse_mode="HTML",
                          disable_web_page_preview=True)
            except Exception as exc:
                log.warning("telegram HTML gönderimi başarısız (%s); düz metin deneniyor", exc)
                try:
                    self.call("sendMessage", chat_id=chat, text=strip_html(chunk), disable_web_page_preview=True)
                except Exception as exc2:
                    log.error("telegram gönderilemedi: %s", exc2)
                    ok = False
        return ok

    CAPTION_LIMIT = 1024   # Telegram: başlık, biçim etiketleri ayıklandıktan sonra en fazla 1024 karakter

    def send_photo(self, photo_url: str, caption: str, subject: str = "m2kira", chat_id: Optional[str] = None) -> bool:
        """İlan kartını fotoğrafla gönderir. Fotoğrafı Telegram'ın sunucusu indirir; indiremezse ya da başlık
        sınırı aşılırsa kart her zamanki gibi düz mesaj olarak gider."""
        targets = self._targets(subject, chat_id)
        if not targets or not photo_url or len(strip_html(caption)) > self.CAPTION_LIMIT:
            return self.send(caption, subject, chat_id=chat_id)
        results = []
        for chat in targets:
            try:
                self.call("sendPhoto", chat_id=chat, photo=photo_url, caption=caption, parse_mode="HTML")
                results.append(True)
            except Exception as exc:  # noqa: BLE001
                log.info("fotoğraflı kart gönderilemedi (%s); düz mesaj gönderiliyor", exc)
                results.append(self._send_one(chat, caption))
        return results[0]

    def get_updates(self, offset: Optional[int], timeout: int = 30) -> list[dict[str, Any]]:
        r = requests.get(f"{self.api}/getUpdates",
                         params={"offset": offset, "timeout": timeout, "allowed_updates": '["message"]'},
                         timeout=timeout + 10)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram getUpdates: {data.get('description')}")
        return data["result"]
