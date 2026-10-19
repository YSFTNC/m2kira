"""SQLite saklama: ilanlar, fiyat geçmişi, olaylar (yeni/düşüş/kalkma), ayarlar, tarama günlüğü."""
from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import Event, Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  url TEXT,
  title TEXT,
  price INTEGER,
  currency TEXT,
  price_includes TEXT,
  rooms TEXT,
  m2_gross INTEGER,
  m2_net INTEGER,
  floor TEXT,
  floor_no INTEGER,
  building_age TEXT,
  heating TEXT,
  elevator INTEGER,
  furnished TEXT,
  furnished_src INTEGER,
  district TEXT,
  county TEXT,
  street TEXT,
  lat REAL,
  lon REAL,
  listed_date TEXT,
  updated_date TEXT,
  office TEXT,
  owner_type TEXT,
  category TEXT,
  description TEXT,
  flags TEXT,
  extras TEXT,
  neighborhood_key TEXT,
  scan_key TEXT,
  nearest_station TEXT,
  distance_m INTEGER,
  walk_minutes_est INTEGER,
  distance_verified INTEGER DEFAULT 0,
  detail_fetched INTEGER DEFAULT 0,
  matches INTEGER DEFAULT 0,
  match_tier TEXT,
  first_seen TEXT,
  last_seen TEXT,
  active INTEGER DEFAULT 1,
  hidden INTEGER DEFAULT 0,
  miss_count INTEGER DEFAULT 0,
  notified_at TEXT,
  dup_of TEXT
);
CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(active, matches, price);
CREATE TABLE IF NOT EXISTS price_history (
  listing_id TEXT NOT NULL,
  price INTEGER,
  seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_hist ON price_history(listing_id, seen_at);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  old_price INTEGER,
  new_price INTEGER,
  created_at TEXT NOT NULL,
  notified INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS scan_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT,
  finished_at TEXT,
  source TEXT,
  neighborhood TEXT,
  pages INTEGER,
  items INTEGER,
  complete INTEGER,
  error TEXT
);
CREATE TABLE IF NOT EXISTS notices (
  key TEXT PRIMARY KEY,
  sent_at TEXT
);
"""

LISTING_COLUMNS = [
    "id", "source", "source_id", "url", "title", "price", "currency", "price_includes", "rooms",
    "m2_gross", "m2_net", "floor", "floor_no", "building_age", "heating", "elevator", "furnished",
    "furnished_src", "district", "county", "street", "lat", "lon", "listed_date", "updated_date",
    "office", "owner_type", "category", "description", "flags", "extras", "neighborhood_key",
    "scan_key", "nearest_station", "distance_m", "walk_minutes_est", "distance_verified", "detail_fetched",
    "matches", "match_tier",
]
# eski veritabanlarına sonradan eklenen sütunlar
MIGRATIONS = [("listings", "scan_key", "TEXT")]
JSON_COLUMNS = {"price_includes", "flags", "extras", "dup_of"}
# detaydan gelen ve liste taramasında boş gelebilecek alanlar: yeni değer None ise eskisini koru
STICKY_COLUMNS = {"description", "lat", "lon", "heating", "building_age", "elevator", "m2_net", "m2_gross",
                  "furnished_src", "office", "floor", "floor_no", "listed_date", "rooms", "district"}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _enc(col: str, v: Any) -> Any:
    if col in JSON_COLUMNS:
        return json.dumps(v if v is not None else ([] if col != "extras" else {}), ensure_ascii=False)
    if isinstance(v, bool):
        return int(v)
    return v


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for c in JSON_COLUMNS:
        if c in d and isinstance(d[c], str):
            try:
                d[c] = json.loads(d[c])
            except Exception:
                d[c] = [] if c != "extras" else {}
    for c in ("elevator", "furnished_src"):
        if c in d and d[c] is not None:
            d[c] = bool(d[c])
    for c in ("distance_verified", "detail_fetched", "matches"):
        if c in d:
            d[c] = bool(d[c])
    return d


def row_to_listing(row: sqlite3.Row | dict) -> Listing:
    d = row_to_dict(row) if isinstance(row, sqlite3.Row) else dict(row)
    return Listing.from_dict(d)


class DB:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        for table, col, typ in MIGRATIONS:
            cols = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self.conn.execute("UPDATE listings SET scan_key=neighborhood_key WHERE scan_key IS NULL")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_scan ON listings(source, scan_key, active)")
        self.conn.commit()

    def checkpoint(self) -> None:
        """WAL'ı ana dosyaya yaz (GitHub Actions'ta yalnız .sqlite dosyası önbelleğe alınır)."""
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass

    def close(self) -> None:
        self.checkpoint()
        self.conn.close()

    # ------------------------------------------------------------------ ilanlar
    def get(self, listing_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
        return row_to_dict(row) if row else None

    def find_by_source_id(self, source_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM listings WHERE source_id=? OR id=?", (source_id, source_id)).fetchall()
        return [row_to_dict(r) for r in rows]

    def upsert(self, l: Listing, now: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Ekler/günceller; önceki satırı (varsa) döndürür. Yapışkan alanlarda None eskisini ezmez."""
        now = now or utcnow()
        old = self.get(l.id)
        vals = {c: getattr(l, c) for c in LISTING_COLUMNS}
        if old:
            for c in STICKY_COLUMNS:
                if vals.get(c) in (None, "", []) and old.get(c) not in (None, ""):
                    vals[c] = old[c]
            if old.get("detail_fetched") and not l.detail_fetched:
                vals["detail_fetched"] = True
                if old.get("extras"):
                    merged = dict(old["extras"])
                    merged.update(l.extras or {})
                    vals["extras"] = merged
            sets = ", ".join(f"{c}=?" for c in LISTING_COLUMNS if c != "id")
            params = [_enc(c, vals[c]) for c in LISTING_COLUMNS if c != "id"]
            self.conn.execute(
                f"UPDATE listings SET {sets}, last_seen=?, active=1, miss_count=0 WHERE id=?",
                params + [now, l.id],
            )
        else:
            cols = LISTING_COLUMNS + ["first_seen", "last_seen", "active", "miss_count"]
            params = [_enc(c, vals[c]) for c in LISTING_COLUMNS] + [now, now, 1, 0]
            self.conn.execute(
                f"INSERT INTO listings ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", params
            )
        self.conn.commit()
        return old

    def update_fields(self, listing_id: str, **fields: Any) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE listings SET {sets} WHERE id=?", [_enc(k, v) for k, v in fields.items()] + [listing_id])
        self.conn.commit()

    def active_listings(self, matches_only: bool = False, include_hidden: bool = False,
                        source: Optional[str] = None, neighborhood_key: Optional[str] = None,
                        max_price: Optional[int] = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM listings WHERE active=1"
        params: list[Any] = []
        if matches_only:
            q += " AND matches=1"
        if not include_hidden:
            q += " AND hidden=0"
        if source:
            q += " AND source=?"
            params.append(source)
        if neighborhood_key:
            q += " AND neighborhood_key=?"
            params.append(neighborhood_key)
        if max_price:
            q += " AND price<=?"
            params.append(max_price)
        q += " ORDER BY price ASC"
        return [row_to_dict(r) for r in self.conn.execute(q, params).fetchall()]

    def mark_missing(self, source: str, scan_key: str, seen_ids: Iterable[str],
                     threshold: int = 2, now: Optional[str] = None) -> list[dict[str, Any]]:
        """Bu tarama biriminde (source + scan_key) görülmeyen aktif ilanların miss_count'unu artırır;
        eşiği aşanları pasife alır ve döndürür."""
        now = now or utcnow()
        seen = set(seen_ids)
        rows = self.conn.execute(
            "SELECT * FROM listings WHERE active=1 AND source=? AND scan_key=?", (source, scan_key)
        ).fetchall()
        removed: list[dict[str, Any]] = []
        for r in rows:
            if r["id"] in seen:
                continue
            miss = int(r["miss_count"] or 0) + 1
            if miss >= threshold:
                self.conn.execute("UPDATE listings SET active=0, miss_count=? WHERE id=?", (miss, r["id"]))
                removed.append(row_to_dict(r))
            else:
                self.conn.execute("UPDATE listings SET miss_count=? WHERE id=?", (miss, r["id"]))
        self.conn.commit()
        return removed

    def set_hidden(self, listing_id: str, hidden: bool = True) -> bool:
        cur = self.conn.execute("UPDATE listings SET hidden=? WHERE id=?", (1 if hidden else 0, listing_id))
        self.conn.commit()
        return cur.rowcount > 0

    def set_notified(self, listing_id: str, now: Optional[str] = None) -> None:
        self.conn.execute("UPDATE listings SET notified_at=? WHERE id=?", (now or utcnow(), listing_id))
        self.conn.commit()

    # ------------------------------------------------------------------ fiyat geçmişi
    def add_price(self, listing_id: str, price: Optional[int], now: Optional[str] = None) -> None:
        self.conn.execute("INSERT INTO price_history (listing_id, price, seen_at) VALUES (?,?,?)",
                          (listing_id, price, now or utcnow()))
        self.conn.commit()

    def price_history(self, listing_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT price, seen_at FROM price_history WHERE listing_id=? ORDER BY seen_at",
                                 (listing_id,)).fetchall()
        return [dict(r) for r in rows]

    def median_price(self, neighborhood_key: str, rooms: Optional[str] = None, min_samples: int = 5) -> Optional[float]:
        q = "SELECT price FROM listings WHERE active=1 AND price IS NOT NULL AND neighborhood_key=?"
        params: list[Any] = [neighborhood_key]
        if rooms:
            q += " AND rooms=?"
            params.append(rooms)
        prices = [r[0] for r in self.conn.execute(q, params).fetchall() if r[0]]
        if len(prices) < min_samples:
            return None
        return float(statistics.median(prices))

    # ------------------------------------------------------------------ olaylar
    def add_event(self, ev: Event) -> int:
        cur = self.conn.execute(
            "INSERT INTO events (listing_id, kind, old_price, new_price, created_at) VALUES (?,?,?,?,?)",
            (ev.listing_id, ev.kind, ev.old_price, ev.new_price, ev.created_at or utcnow()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def pending_events(self) -> list[Event]:
        rows = self.conn.execute("SELECT * FROM events WHERE notified=0 ORDER BY id").fetchall()
        return [Event(id=r["id"], listing_id=r["listing_id"], kind=r["kind"], old_price=r["old_price"],
                      new_price=r["new_price"], created_at=r["created_at"]) for r in rows]

    def mark_events_notified(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if ids:
            self.conn.executemany("UPDATE events SET notified=1 WHERE id=?", [(i,) for i in ids])
            self.conn.commit()

    def recent_events(self, hours: int = 24) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT e.*, l.title, l.price AS cur_price, l.source FROM events e JOIN listings l ON l.id=e.listing_id "
            "WHERE e.created_at >= datetime('now', ?) ORDER BY e.id DESC", (f"-{int(hours)} hours",)
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ ayarlar / bildirim kilitleri
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not row or row[0] is None:
            return default
        try:
            return json.loads(row[0])
        except Exception:
            return row[0]

    def set_setting(self, key: str, value: Any) -> None:
        self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                          (key, json.dumps(value, ensure_ascii=False)))
        self.conn.commit()

    def notice_due(self, key: str, min_hours: float) -> bool:
        """Aynı uyarının (ör. parser hatası) en az `min_hours` arayla gönderilmesini sağlar."""
        row = self.conn.execute("SELECT sent_at FROM notices WHERE key=?", (key,)).fetchone()
        if row and row[0]:
            last = datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - last).total_seconds() < min_hours * 3600:
                return False
        self.conn.execute("INSERT OR REPLACE INTO notices (key, sent_at) VALUES (?,?)", (key, utcnow()))
        self.conn.commit()
        return True

    # ------------------------------------------------------------------ tarama günlüğü
    def log_scan(self, started_at: str, source: str, neighborhood: str, pages: int, items: int,
                 complete: bool, error: Optional[str]) -> None:
        self.conn.execute(
            "INSERT INTO scan_log (started_at, finished_at, source, neighborhood, pages, items, complete, error) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (started_at, utcnow(), source, neighborhood, pages, items, 1 if complete else 0, error),
        )
        self.conn.commit()

    def last_scan_info(self) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT started_at, MAX(finished_at) AS finished_at, SUM(items) AS items, SUM(pages) AS pages, "
            "SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors FROM scan_log "
            "WHERE started_at=(SELECT MAX(started_at) FROM scan_log)"
        ).fetchone()
        return dict(row) if row and row["started_at"] else None

    def counts(self) -> dict[str, int]:
        row = self.conn.execute(
            "SELECT COUNT(*) AS total, SUM(active) AS active, SUM(CASE WHEN active=1 AND matches=1 AND hidden=0 THEN 1 ELSE 0 END) AS matching "
            "FROM listings"
        ).fetchone()
        return {k: int(row[k] or 0) for k in row.keys()}
