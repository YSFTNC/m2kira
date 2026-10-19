"""sahibinden — e-posta bildirimi kaynağı (sunucu dostu).

sahibinden arama sonuçları bot koruması (Cloudflare + PerimeterX) ve zorunlu üye girişi yüzünden
sunucuda otomatik gezilemiyor. Bunun yerine sahibinden'in kendi özelliği kullanılır: siteye girip
aramayı (ör. Çankaya > Kiralık Daire > Eşyalı, fiyat ≤ 39.000, mahalleler) "Favori Aramalarım"a
kaydedip e-posta bildirimini açarsınız; yeni ilan geldikçe sahibinden e-posta gönderir.

Bu modül o e-postaları IMAP ile okur, içindeki ilan linklerini/fiyatları çıkarır, veritabanına
"sahibinden:<ilanNo>" olarak yazar ve diğer kaynaklarla aynı bildirim akışına sokar. E-posta
şablonu değişse de link çıkarma (https://www.sahibinden.com/ilan/...-<id>) çalışmaya devam eder.

Ayarlar: .env -> IMAP_HOST (imap.gmail.com), IMAP_USER, IMAP_PASSWORD (Gmail: uygulama şifresi),
IMAP_FOLDER (INBOX). config.yaml -> sources.sahibinden_mail.
"""
from __future__ import annotations

import email
import imaplib
import logging
import re
from email.header import decode_header, make_header
from email.message import Message
from typing import Any, Optional
from urllib.parse import unquote

from bs4 import BeautifulSoup

from ..http import SourceError
from ..models import Listing, ScanResult
from ..textnorm import normalize_rooms, parse_price
from .base import Source

log = logging.getLogger(__name__)

LINK_RE = re.compile(r"https?://(?:www\.)?sahibinden\.com/ilan/([^\s\"'<>?#]*?-(\d{6,12}))(?:/detay)?(?=[\s\"'<>?#/]|$)", re.I)
PRICE_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d{4,7})\s*(?:TL|₺)")
_WS = re.compile(r"\s+")


def _decode(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _body_parts(msg: Message) -> tuple[str, str]:
    """(html, text)"""
    html, text = "", ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        ctype = part.get_content_type()
        if ctype not in ("text/html", "text/plain"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
        except Exception:
            continue
        if ctype == "text/html":
            html += decoded
        else:
            text += decoded
    return html, text


def extract_listings(html: str, text: str = "", subject: str = "") -> list[Listing]:
    """E-posta gövdesinden sahibinden ilanlarını çıkarır. Takip (redirect) linklerindeki
    URL-encoded hedefler de çözülür."""
    found: dict[str, dict[str, Any]] = {}

    def add(sid: str, slug: str, title: str, ctx: str) -> None:
        e = found.setdefault(sid, {"url": f"https://www.sahibinden.com/ilan/{slug}/detay", "title": "", "price": None, "ctx": ""})
        title = _WS.sub(" ", title or "").strip()
        if title and len(title) > len(e["title"]) and not re.fullmatch(r"[\d.\s]+(?:TL|₺)?", title) and "http" not in title:
            e["title"] = title[:200]
        if ctx and len(ctx) > len(e["ctx"]):
            e["ctx"] = _WS.sub(" ", ctx)[:600]
        if e["price"] is None:
            pm = PRICE_RE.search(ctx or "")
            if pm:
                e["price"] = parse_price(pm.group(0))

    if html:
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href = unquote(a["href"])
            m = LINK_RE.search(href)
            if not m:
                continue
            container = a.find_parent(["tr", "li", "td", "div"]) or a
            ctx = container.get_text(" ", strip=True)
            add(m.group(2), m.group(1), a.get_text(" ", strip=True), ctx)
    for m in LINK_RE.finditer(unquote(text or "")):
        s = max(0, m.start() - 300)
        add(m.group(2), m.group(1), "", text[s:m.end() + 300])
    out: list[Listing] = []
    for sid, e in found.items():
        title = e["title"] or subject or f"sahibinden ilanı {sid}"
        out.append(Listing(
            source="sahibinden",
            source_id=sid,
            url=e["url"],
            title=title,
            price=e["price"],
            rooms=normalize_rooms(re.search(r"\b\d(?:[.,]5)?\s*\+\s*\d\b|st[üu]dyo", e["ctx"] or title, re.I).group(0)) if re.search(r"\b\d(?:[.,]5)?\s*\+\s*\d\b|st[üu]dyo", e["ctx"] or title, re.I) else None,
            description=e["ctx"],
            extras={"via": "mail"},
        ))
    return out


class MailClient:
    def __init__(self, host: str, user: str, password: str, folder: str = "INBOX", port: int = 993):
        self.host, self.user, self.password, self.folder, self.port = host, user, password, folder, port

    def fetch(self, since_uid: Optional[int], lookback_days: int, sender: str = "sahibinden") -> list[dict[str, Any]]:
        from datetime import datetime, timedelta
        out: list[dict[str, Any]] = []
        try:
            M = imaplib.IMAP4_SSL(self.host, self.port)
            M.login(self.user, self.password)
        except Exception as exc:
            raise SourceError(f"IMAP bağlantısı/girişi başarısız ({self.host}): {exc}") from exc
        try:
            typ, _ = M.select(self.folder, readonly=True)
            if typ != "OK":
                raise SourceError(f"IMAP klasörü açılamadı: {self.folder}")
            since = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
            criteria = f'(FROM "{sender}" SINCE {since})'
            if since_uid:
                criteria = f'(UID {int(since_uid) + 1}:* FROM "{sender}")'
            typ, data = M.uid("search", None, criteria)
            if typ != "OK":
                raise SourceError("IMAP arama başarısız")
            uids = [int(u) for u in (data[0] or b"").split()]
            for uid in uids:
                if since_uid and uid <= since_uid:
                    continue
                typ, msgdata = M.uid("fetch", str(uid), "(RFC822)")
                if typ != "OK" or not msgdata or not msgdata[0]:
                    continue
                raw = msgdata[0][1]
                msg = email.message_from_bytes(raw)
                html, text = _body_parts(msg)
                out.append({"uid": uid, "subject": _decode(msg.get("Subject")), "from": _decode(msg.get("From")),
                            "date": msg.get("Date"), "html": html, "text": text})
        finally:
            try:
                M.logout()
            except Exception:
                pass
        return out


class SahibindenMailSource(Source):
    name = "sahibinden_mail"
    supports_detail = False
    per_neighborhood = False   # mahalle mahalle değil, tek seferde
    site_scraper = False       # siteye değil e-posta kutusuna bakar

    def __init__(self, cfg):
        super().__init__(cfg)
        self.host = cfg.secret("IMAP_HOST", self.scfg.get("host", "imap.gmail.com")) or "imap.gmail.com"
        self.user = cfg.secret("IMAP_USER", "") or ""
        self.password = cfg.secret("IMAP_PASSWORD", "") or ""
        self.folder = cfg.secret("IMAP_FOLDER", self.scfg.get("folder", "INBOX")) or "INBOX"
        self.sender = str(self.scfg.get("sender", "sahibinden"))
        self.lookback_days = int(self.scfg.get("lookback_days", 2))
        self.assume_furnished = bool(self.scfg.get("assume_furnished", True))

    @property
    def configured(self) -> bool:
        return bool(self.user and self.password)

    def scan_neighborhood(self, nb) -> ScanResult:
        # complete=False: e-postalar yalnızca yeni ilanları getirir, "yayından kalktı" çıkarımı yapılamaz
        result = ScanResult(source=self.name, neighborhood="e-posta", complete=False, scan_key="e-posta")
        if not (self.user and self.password):
            result.errors.append("IMAP_USER / IMAP_PASSWORD tanımlı değil (.env)")
            return result
        last_uid = int(self.db.get_setting("mail_last_uid", 0) or 0) if self.db else 0
        client = MailClient(self.host, self.user, self.password, self.folder)
        mails = client.fetch(last_uid or None, self.lookback_days, self.sender)
        result.pages = len(mails)
        merged: dict[str, Listing] = {}
        max_uid = last_uid
        for m in mails:
            max_uid = max(max_uid, int(m["uid"]))
            for l in extract_listings(m["html"], m["text"], m["subject"]):
                if self.assume_furnished and l.furnished_src is None:
                    l.furnished_src = True
                l.listed_date = l.listed_date or None
                l.extras["mail_subject"] = m["subject"][:120]
                merged.setdefault(l.id, l)
        if self.db and max_uid > last_uid:
            self.db.set_setting("mail_last_uid", max_uid)
        result.listings = list(merged.values())
        log.info("sahibinden e-posta: %d e-posta, %d ilan", len(mails), len(result.listings))
        return result

    def manual_urls(self, nb) -> list[str]:
        return ["https://www.sahibinden.com/favori-aramalarim"]
