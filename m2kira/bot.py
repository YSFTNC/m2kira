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
/durak — durak durak özet (hat sırasıyla)
/filtre [durak] — filtre sayfası linki (ör. /filtre Kızılay)
/tara — şimdi tara
/durum — son tarama, sayılar, hatalar
/davet — arkadaşın için katılma kodu (yalnız sahibi) · /uyeler · /cikar &lt;no&gt;
/ayril — (üye) bildirimleri bırak
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
        self.tg.extra_chats = [m["id"] for m in self._members()]

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
        parts = text.split()
        cmd = parts[0].split("@")[0].lower()
        args = parts[1:]
        owner = chat_id == str(self.tg.chat_id)
        if not owner and not self._is_member(chat_id):
            if cmd in ("/katil", "/katıl"):
                self.cmd_join(msg, chat_id, args)
            else:
                self._reply(msg, "Bu bot özel. Sahibinden katılma kodu iste ve buraya <code>/katil KOD</code> yaz.")
            return
        if cmd == "/davet":
            if owner:
                self.cmd_invite(msg)
            else:
                self._reply(msg, "Davet kodunu yalnız botun sahibi oluşturabilir.")
        elif cmd in ("/uyeler", "/üyeler"):
            self._reply(msg, self.members_text())
        elif cmd in ("/cikar", "/çıkar") and owner:
            self.cmd_remove(msg, args)
        elif cmd in ("/ayril", "/ayrıl") and not owner:
            self._set_members([m for m in self._members() if m["id"] != chat_id])
            self._reply(msg, "Bildirimler durduruldu. Yeniden katılmak için yeni bir kod gerekir.")
        elif cmd in ("/katil", "/katıl"):
            self._reply(msg, "Zaten bildirimleri alıyorsun.")
        elif cmd in ("/start", "/yardim", "/help"):
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
        elif cmd == "/durak":
            self._reply(msg, self.p.station_overview())
        elif cmd in ("/filtre", "/sayfa", "/web"):
            self.cmd_filtre(msg, args)
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

    # ---- üyeler (arkadaş): davet koduyla katılır, ilan bildirimlerini ve komutları kullanır
    INVITE_HOURS = 48

    def _members(self) -> list[dict[str, str]]:
        raw = self.p.db.get_setting("tg_members", []) or []
        return [m for m in raw if isinstance(m, dict) and m.get("id")]

    def _set_members(self, members: list[dict[str, str]]) -> None:
        self.p.db.set_setting("tg_members", members)
        self.tg.extra_chats = [m["id"] for m in members]

    def _is_member(self, chat_id: str) -> bool:
        return any(m["id"] == chat_id for m in self._members())

    def members_text(self) -> str:
        ms = self._members()
        if not ms:
            return "Henüz üye yok. Arkadaşını eklemek için /davet yaz."
        lines = ["<b>👥 Bildirim alan üyeler</b>"] + [f"{i}. {esc(m.get('name') or m['id'])}" for i, m in enumerate(ms, 1)]
        return "\n".join(lines + ["Çıkarmak için: /cikar &lt;no&gt;"])

    def cmd_invite(self, msg: dict[str, Any]) -> None:
        import secrets
        from datetime import datetime, timedelta, timezone
        code = f"{secrets.randbelow(900000) + 100000}"
        until = (datetime.now(timezone.utc) + timedelta(hours=self.INVITE_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.p.db.set_setting("tg_invite", {"code": code, "until": until})
        bot_name = str(self.p.cfg.get("web", "telegram_bot", default="") or "")
        where = f"@{bot_name}" if bot_name else "bota"
        self._reply(msg, f"👥 Arkadaşın {esc(where)} adresine şunu yazsın:\n<code>/katil {code}</code>\n"
                         f"Kod {self.INVITE_HOURS} saat geçerli ve bir kez kullanılır. Komutlar ~30 dakikada bir işlendiği için "
                         "onay mesajı biraz gecikebilir.")

    def cmd_join(self, msg: dict[str, Any], chat_id: str, args: list[str]) -> None:
        from datetime import datetime, timezone
        inv = self.p.db.get_setting("tg_invite") or {}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not args or not inv.get("code") or args[0].strip() != inv["code"] or now > str(inv.get("until") or ""):
            self._reply(msg, "Kod geçersiz ya da süresi dolmuş. Botun sahibinden yeni kod iste (/davet).")
            return
        frm = msg.get("from") or {}
        name = " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x) or frm.get("username") or chat_id
        self._set_members(self._members() + [{"id": chat_id, "name": str(name)[:60]}])
        self.p.db.set_setting("tg_invite", {})
        self._reply(msg, "✅ Katıldın. Yeni ilan, fiyat düşüşü ve değişiklik bildirimleri artık sana da gelecek.\n\n" + HELP)
        try:
            self.tg.send(f"👥 <b>{esc(name)}</b> bildirimlere katıldı. Üyeler: /uyeler", chat_id=str(self.tg.chat_id))
        except Exception:  # noqa: BLE001
            pass

    def cmd_remove(self, msg: dict[str, Any], args: list[str]) -> None:
        ms = self._members()
        if not args or not args[0].isdigit() or not 1 <= int(args[0]) <= len(ms):
            self._reply(msg, self.members_text())
            return
        gone = ms.pop(int(args[0]) - 1)
        self._set_members(ms)
        self._reply(msg, f"{esc(gone.get('name') or gone['id'])} çıkarıldı.")

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

    def cmd_filtre(self, msg: dict[str, Any], args: list[str]) -> None:
        if not self.p.web_link():
            self._reply(msg, "Filtre sayfası adresi config.yaml'da (web.url) tanımlı değil.")
            return
        if args:
            st = self.p.stations.get(" ".join(args))
            if st and st.line == "M2":
                self._reply(msg, f'🔎 <a href="{esc(self.p.web_link(st=st.name))}">{esc(st.name)} ilanları</a>')
                return
            self._reply(msg, f"Durak bulunamadı: {esc(' '.join(args))}. Tüm ilanlar:\n{esc(self.p.web_link())}")
            return
        self._reply(msg, f'🔎 <a href="{esc(self.p.web_link())}">Filtre sayfası</a>\n'
                         "Durak durak görünüm, fiyat/oda/eşya/yürüme filtreleri, işe ulaşım süresi, harita.")

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


def attach_members(notifier: Any, db: Any) -> None:
    """Pipeline bildirimleri /davet ile katılan üyelere de gitsin (teknik uyarılar hariç)."""
    from .notify.base import MultiNotifier
    tgs = [notifier] if isinstance(notifier, TelegramNotifier) else (
        [n for n in notifier.notifiers if isinstance(n, TelegramNotifier)] if isinstance(notifier, MultiNotifier) else [])
    members = [m["id"] for m in (db.get_setting("tg_members", []) or []) if isinstance(m, dict) and m.get("id")]
    for t in tgs:
        t.extra_chats = members
