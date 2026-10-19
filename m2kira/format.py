"""Telegram/e-posta/ntfy için metin biçimlendirme (Telegram HTML alt kümesi)."""
from __future__ import annotations

import html
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Optional

from .textnorm import FLAG_LABELS, FURNISHED_LABELS

SOURCE_LABEL = {"hepsiemlak": "hepsiemlak", "emlakjet": "emlakjet", "sahibinden": "sahibinden"}
EVENT_HEAD = {
    "new": "🆕 Yeni ilan",
    "reappeared": "♻️ Yeniden yayında",
    "price_drop": "💸 Fiyat düştü",
    "price_up": "📈 Fiyat arttı",
    "removed": "❌ Yayından kalktı",
    "now_matches": "✅ Artık kriterlere uyuyor",
}


def esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""), quote=False)


def fmt_price(p: Optional[int]) -> str:
    if p is None:
        return "fiyat yok"
    return f"{p:,.0f}".replace(",", ".") + " TL"


def fmt_date(d: Optional[str]) -> str:
    if not d:
        return ""
    try:
        return datetime.strptime(d[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return d


def short_id(listing_id: str) -> str:
    src, _, sid = listing_id.partition(":")
    return f"{ {'hepsiemlak': 'he', 'emlakjet': 'ej', 'sahibinden': 'sb'}.get(src, src)}:{sid}"


def long_id(short: str) -> str:
    src, _, sid = short.partition(":")
    return f"{ {'he': 'hepsiemlak', 'ej': 'emlakjet', 'sb': 'sahibinden'}.get(src, src)}:{sid}"


def station_line(l: dict[str, Any]) -> str:
    st = l.get("nearest_station") or "?"
    if l.get("distance_verified") and l.get("distance_m") is not None:
        return f"M2 {esc(st)} 🚶 ~{l.get('walk_minutes_est')} dk ({l['distance_m']} m)"
    return f"M2 {esc(st)} (mesafe doğrulanmadı)"


def flag_labels(flags: Iterable[str]) -> list[str]:
    out = []
    for f in flags or []:
        if f.startswith("kopya:"):
            out.append("muhtemel kopya: " + f.split(":", 1)[1])
        else:
            out.append(FLAG_LABELS.get(f, f))
    return out


def format_listing(l: dict[str, Any], event: Optional[dict[str, Any]] = None, budget: Optional[int] = None) -> str:
    head = ""
    if event:
        head = EVENT_HEAD.get(event.get("kind", ""), event.get("kind", ""))
        if event.get("kind") in ("price_drop", "price_up") and event.get("old_price"):
            head += f": {fmt_price(event['old_price'])} → {fmt_price(event['new_price'])}"
        if event.get("fav"):
            head = "⭐ " + head + " (favori)"
    tier = ""
    if l.get("match_tier") == "pazarlikla":
        tier = " 🤝 bütçe üstü, pazarlıkla"
    elif budget and l.get("price") and l["price"] > budget:
        tier = " (bütçe üstü)"
    parts = [f"<b>{fmt_price(l.get('price'))}</b>{tier}"]
    spec = " · ".join(x for x in [
        l.get("rooms"),
        (f"{l['m2_gross']} m²" + (f" (net {l['m2_net']})" if l.get("m2_net") else "")) if l.get("m2_gross") else None,
        l.get("floor"),
        f"bina {l['building_age']}" if l.get("building_age") not in (None, "", "0") else None,
    ] if x)
    inc = l.get("price_includes") or []
    inc_txt = {"hepsi": "her şey dahil", "faturalar": "faturalar dahil", "aidat": "aidat dahil", "internet": "internet dahil"}
    furn = FURNISHED_LABELS.get(l.get("furnished") or "unknown", "?")
    lines = [
        (f"<b>{head}</b>\n" if head else "") + f"<b>{esc(l.get('title'))}</b>",
        parts[0] + (f" · {esc(spec)}" if spec else ""),
        f"📍 {esc(l.get('district') or l.get('neighborhood_key') or '?')} → {station_line(l)}",
        "🛋 " + esc(furn) + (" | " + ", ".join(inc_txt.get(i, i) for i in inc) if inc else ""),
    ]
    fl = flag_labels(l.get("flags") or [])
    if fl:
        lines.append("⚠️ " + esc(", ".join(fl)))
    meta = " · ".join(x for x in [
        esc(l.get("office")) if l.get("office") else (esc(l.get("owner_type")) if l.get("owner_type") else None),
        SOURCE_LABEL.get(l.get("source"), l.get("source")),
        fmt_date(l.get("listed_date")),
    ] if x)
    lines.append(f"🏢 {meta}")
    lines.append(f"🔗 {esc(l.get('url'))}")
    lines.append(f"<code>/gizle {short_id(l['id'])}</code>")
    return "\n".join(lines)


def format_line(l: dict[str, Any]) -> str:
    st = l.get("nearest_station") or "?"
    walk = f"~{l['walk_minutes_est']}dk" if l.get("distance_verified") and l.get("walk_minutes_est") else "?dk"
    furn = {"full": "eşyalı", "partial": "kısmi", "either": "eşyalı/sız", "none": "eşyasız", "unknown": "?"}.get(l.get("furnished"), "?")
    tier = " 🤝" if l.get("match_tier") == "pazarlikla" else ""
    flags = l.get("flags") or []
    warn = " ⚠️" if any(f in flags for f in ("kisit", "acil", "kapora", "depozitosuz", "kot_bodrum", "fiyat_cok_dusuk", "ankaray_uyari", "kisa_sureli")) else ""
    return (f"• <b>{fmt_price(l.get('price'))}</b>{tier} · {esc(l.get('rooms') or '?')} · "
            f"{l.get('m2_gross') or '?'} m² · {esc(l.get('district') or '?')} → {esc(st)} {walk} · {furn}{warn}\n"
            f"  <a href=\"{esc(l.get('url'))}\">{esc(SOURCE_LABEL.get(l.get('source'), l.get('source')))}</a> "
            f"<code>{short_id(l['id'])}</code>")


def format_summary(listings: list[dict[str, Any]], budget: int, title: str = "Günlük özet", limit: int = 40) -> str:
    by_station: dict[str, list[int]] = defaultdict(list)
    for l in listings:
        if l.get("price"):
            by_station[l.get("nearest_station") or "?"].append(l["price"])
    head = [f"<b>📋 {esc(title)}</b> — bütçe {fmt_price(budget)}", f"Aktif uygun ilan: <b>{len(listings)}</b>"]
    if by_station:
        head.append("")
        head.append("<b>İstasyon bazında</b> (adet · en ucuz · medyan)")
        for st, prices in sorted(by_station.items(), key=lambda kv: -len(kv[1])):
            head.append(f"• {esc(st)}: {len(prices)} · {fmt_price(min(prices))} · {fmt_price(int(statistics.median(prices)))}")
    body = [format_line(l) for l in listings[:limit]]
    if len(listings) > limit:
        body.append(f"… ve {len(listings) - limit} ilan daha (/liste {len(listings)})")
    return "\n".join(head + [""] + body) if body else "\n".join(head + ["", "Şu an kriterlere uyan aktif ilan yok."])


def split_message(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks
