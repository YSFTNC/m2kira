"""Telegram komutları (long polling, ayrı thread). Taramalar ana thread'de (zamanlayıcı) yürür;
/tara yalnızca istek bayrağını kaldırır."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from .format import esc, fmt_price, format_line, format_listing
from .notify.telegram import TelegramNotifier
from .pipeline import Pipeline

log = logging.getLogger(__name__)

HELP = """<b>m2kira komutları</b>
/liste [n] — bütçe içindeki aktif ilanlar (en ucuz n tanesi, varsayılan 15)
/liste pazarlik — bütçeyi %5'e kadar aşan ilanlar
/liste istasyon &lt;ad&gt; — istasyona göre (ör. /liste istasyon Söğütözü)
/liste mahalle &lt;ad&gt; — mahalleye göre
/ilan &lt;id&gt; — ilan kartı (ör. /ilan he:131733-2621)
/butce 40000 — bütçe tavanını değiştir
/mahalle — izlenen mahalleler · /mahalle ekle &lt;ad&gt; [istasyon] · /mahalle sil &lt;ad&gt;
/gizle &lt;id&gt; · /goster &lt;id&gt; — ilanı gizle / geri getir
/ozet — özet (istasyon bazında sayı, en ucuz, medyan)
/tara — şimdi tara
/durum — son tarama, sayılar, hatalar
/yardim — bu mesaj"""


class TelegramBot:
    def __init__(self, pipeline: Pipeline, tg: TelegramNotifier):
        self.p = pipeline
        self.tg = tg
        self.stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        saved = self.p.db.get_setting("chat_id")
        if not self.tg.chat_id and saved:
            self.tg.chat_id = str(saved)

    # ------------------------------------------------------------------ döngü
    def start(self) -> None:
        self._thread = threading.Thread(target=self.run_forever, name="telegram-bot", daemon=True)
        self._thread.start()

    def poll_once(self) -> int:
        """Birikmiş komutları bir kez işler (cron/GitHub Actions modu). İşlenen mesaj sayısını döndürür."""
        offset = self.p.db.get_setting("tg_offset")
        offset = int(offset) if offset else None
        try:
            updates = self.tg.get_updates(offset, timeout=1)
        except Exception as exc:  # noqa: BLE001
            log.warning("getUpdates hatası: %s", exc)
            return 0
        n = 0
        for u in updates:
            offset = int(u["update_id"]) + 1
            msg = u.get("message") or {}
            try:
                self.handle(msg)
                n += 1
            except Exception as exc:  # noqa: BLE001
                log.exception("komut hatası")
                self._reply(msg, f"Hata: {esc(exc)}")
        if offset is not None:
            self.p.db.set_setting("tg_offset", offset)
        return n

    def run_forever(self) -> None:
        offset: Optional[int] = None
        log.info("telegram bot dinliyor")
        while not self.stop.is_set():
            try:
                updates = self.tg.get_updates(offset, timeout=30)
            except Exception as exc:  # noqa: BLE001
                log.warning("getUpdates hatası: %s", exc)
                time.sleep(5)
                continue
            for u in updates:
                offset = int(u["update_id"]) + 1
                msg = u.get("message") or {}
                try:
                    self.handle(msg)
                except Exception as exc:  # noqa: BLE001
                    log.exception("komut hatası")
                    self._reply(msg, f"Hata: {esc(exc)}")

    # ------------------------------------------------------------------ komutlar
    def _reply(self, msg: dict[str, Any], text: str) -> None:
        chat = str((msg.get("chat") or {}).get("id") or self.tg.chat_id)
        self.tg.send(text, chat_id=chat)

    def handle(self, msg: dict[str, Any]) -> None:
        text = (msg.get("text") or "").strip()
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        if not text or not chat_id:
            return
        if not self.tg.chat_id:
            self.tg.chat_id = chat_id
            self.p.db.set_setting("chat_id", chat_id)
            self._reply(msg, f"Bu sohbet kaydedildi (chat id <code>{chat_id}</code>). Bildirimler buraya gelecek.\n\n" + HELP)
            return
        if chat_id != str(self.tg.chat_id):
            self._reply(msg, "Bu bot yalnızca sahibine yanıt verir.")
            return
        parts = text.split()
        cmd = parts[0].split("@")[0].lower()
        args = parts[1:]
        if cmd in ("/start", "/yardim", "/help"):
            self._reply(msg, HELP)
        elif cmd == "/liste":
            self.cmd_liste(msg, args)
        elif cmd == "/ilan":
            self.cmd_ilan(msg, args)
        elif cmd in ("/butce", "/bütçe"):
            self.cmd_butce(msg, args)
        elif cmd == "/mahalle":
            self.cmd_mahalle(msg, args)
        elif cmd == "/gizle":
            self.cmd_hide(msg, args, True)
        elif cmd == "/goster":
            self.cmd_hide(msg, args, False)
        elif cmd in ("/ozet", "/özet"):
            self._reply(msg, self.p.summary_text(title="Özet"))
        elif cmd == "/tara":
            if self.p.lock.locked():
                self._reply(msg, "Tarama zaten sürüyor.")
            else:
                self.p.scan_requested.set()
                self._reply(msg, "Tarama sıraya alındı; bitince sonuç gelecek." if self._thread
                            else "Not alındı; bir sonraki zamanlanmış taramada işlenecek.")
        elif cmd == "/durum":
            self._reply(msg, self.p.status_text())
        else:
            self._reply(msg, "Anlaşılmadı. /yardim")

    def cmd_liste(self, msg: dict[str, Any], args: list[str]) -> None:
        n = 15
        station = neighborhood = tier = None
        max_price: Optional[int] = self.p.budget()
        if args:
            if args[0].isdigit():
                n = int(args[0])
            elif args[0].lower() in ("pazarlik", "pazarlık"):
                tier = "pazarlikla"
                max_price = None
            elif args[0].lower() == "istasyon" and len(args) > 1:
                station = " ".join(args[1:])
            elif args[0].lower() == "mahalle" and len(args) > 1:
                neighborhood = " ".join(args[1:])
            elif args[0].lower() in ("hepsi", "tum", "tüm"):
                n = 100
        rows = self.p.matching_listings(max_price=max_price, station=station, neighborhood=neighborhood, tier=tier)
        if not rows:
            self._reply(msg, "Kriterlere uyan aktif ilan yok.")
            return
        head = f"<b>{len(rows)} ilan</b> (bütçe {fmt_price(self.p.budget())}), en ucuz {min(n, len(rows))}:"
        self._reply(msg, head + "\n" + "\n".join(format_line(r) for r in rows[:n]))

    def cmd_ilan(self, msg: dict[str, Any], args: list[str]) -> None:
        if not args:
            self._reply(msg, "Kullanım: /ilan he:131733-2621")
            return
        from .format import long_id
        lid = long_id(args[0]) if ":" in args[0] else None
        row = self.p.db.get(lid) if lid else None
        if not row:
            rows = self.p.db.find_by_source_id(args[0])
            row = rows[0] if rows else None
        if not row:
            self._reply(msg, "İlan bulunamadı.")
            return
        hist = self.p.db.price_history(row["id"])
        text = format_listing(row, None, self.p.budget())
        if len(hist) > 1:
            text += "\n📊 Fiyat geçmişi: " + " → ".join(fmt_price(h["price"]) for h in hist)
        if not row.get("active"):
            text += "\n❌ Şu an yayında değil"
        self._reply(msg, text)

    def cmd_butce(self, msg: dict[str, Any], args: list[str]) -> None:
        if not args:
            self._reply(msg, f"Bütçe: {fmt_price(self.p.budget())}. Değiştirmek için: /butce 40000")
            return
        try:
            val = int(args[0].replace(".", "").replace(",", ""))
        except ValueError:
            self._reply(msg, "Sayı bekleniyor, ör. /butce 40000")
            return
        if val < 1000:
            self._reply(msg, "Bütçe TL cinsinden aylık olmalı (ör. 37000).")
            return
        self.p.set_budget(val)
        self._reply(msg, f"Bütçe {fmt_price(val)} olarak ayarlandı. Mevcut ilanlar bir sonraki taramada yeniden değerlendirilecek (/tara).")

    def cmd_mahalle(self, msg: dict[str, Any], args: list[str]) -> None:
        if not args:
            nbs = self.p.neighborhoods()
            self._reply(msg, "<b>İzlenen mahalleler</b>\n" + "\n".join(f"• {esc(n.name)} → {esc(n.station or '?')}" for n in nbs))
            return
        sub = args[0].lower()
        if sub == "ekle" and len(args) > 1:
            name = args[1]
            station = " ".join(args[2:]) if len(args) > 2 else ""
            nb = self.p.add_neighborhood(name, station)
            self._reply(msg, f"Eklendi: {esc(nb.name)} → {esc(nb.station or 'istasyon belirtilmedi')}\n"
                             f"Kaynak slug'ları otomatik türetildi (hepsiemlak: {esc(nb.slug_for('hepsiemlak'))}, "
                             f"emlakjet: {esc(nb.slug_for('emlakjet'))}). Yanlışsa config.yaml'da düzeltin.")
        elif sub == "sil" and len(args) > 1:
            ok = self.p.remove_neighborhood(" ".join(args[1:]))
            self._reply(msg, "Kaldırıldı." if ok else "Böyle bir mahalle yok.")
        else:
            self._reply(msg, "Kullanım: /mahalle · /mahalle ekle Ayrancı Kızılay · /mahalle sil Ayrancı")

    def cmd_hide(self, msg: dict[str, Any], args: list[str], hidden: bool) -> None:
        if not args:
            self._reply(msg, "Kullanım: /gizle he:131733-2621")
            return
        lid = self.p.hide(args[0], hidden)
        if lid:
            self._reply(msg, ("Gizlendi: " if hidden else "Geri getirildi: ") + esc(lid))
        else:
            self._reply(msg, "İlan bulunamadı.")
