"""Channel Hub SQLite schema and persistence helpers (per-bot user_data.db)."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.core.app_paths import PROJECTS_DIR

URL_RE = re.compile(
    r"(?i)((https?://|www\.)\S+|t\.me/\S+|telegram\.me/\S+)"
)

CHANNEL_REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS channel_registry (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    chat_type TEXT,
    username TEXT,
    linked_chat_id INTEGER,
    members_count INTEGER,
    updated_at REAL NOT NULL
)
"""

CHANNEL_POSTS_DDL = """
CREATE TABLE IF NOT EXISTS channel_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    telegram_message_id INTEGER NOT NULL,
    text TEXT,
    full_text TEXT,
    post_url TEXT,
    views_count INTEGER NOT NULL DEFAULT 0,
    forwards_count INTEGER NOT NULL DEFAULT 0,
    comments_count INTEGER NOT NULL DEFAULT 0,
    reactions_count INTEGER NOT NULL DEFAULT 0,
    reactions_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    UNIQUE(channel_id, telegram_message_id)
)
"""

CHANNEL_COMMENTS_DDL = """
CREATE TABLE IF NOT EXISTS channel_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    channel_id INTEGER,
    channel_post_message_id INTEGER,
    telegram_message_id INTEGER NOT NULL,
    user_id INTEGER,
    username TEXT,
    text TEXT,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    moderated INTEGER NOT NULL DEFAULT 0,
    violation_kind TEXT,
    created_at REAL NOT NULL,
    UNIQUE(chat_id, telegram_message_id)
)
"""

CHANNEL_MEMBER_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS channel_member_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER,
    username TEXT,
    event_type TEXT NOT NULL,
    invite_link_used TEXT,
    timestamp REAL NOT NULL
)
"""

USER_WARNINGS_DDL = """
CREATE TABLE IF NOT EXISTS user_warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    warning_count INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    last_warned_at REAL,
    UNIQUE(chat_id, user_id)
)
"""

MODERATION_RULES_DDL = """
CREATE TABLE IF NOT EXISTS moderation_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL UNIQUE,
    forbidden_keywords TEXT NOT NULL DEFAULT '[]',
    block_links INTEGER NOT NULL DEFAULT 1,
    block_stickers INTEGER NOT NULL DEFAULT 0,
    block_media INTEGER NOT NULL DEFAULT 0,
    anti_flood INTEGER NOT NULL DEFAULT 0,
    flood_max_messages INTEGER NOT NULL DEFAULT 5,
    flood_time_window_seconds INTEGER NOT NULL DEFAULT 10,
    flood_action TEXT NOT NULL DEFAULT 'warn',
    warn_decay_hours INTEGER NOT NULL DEFAULT 24,
    instant_mute_on_warn INTEGER NOT NULL DEFAULT 0,
    instant_mute_duration_minutes INTEGER NOT NULL DEFAULT 10,
    allowed_urls_whitelist TEXT NOT NULL DEFAULT '[]',
    max_warnings INTEGER NOT NULL DEFAULT 3,
    mute_duration_minutes INTEGER NOT NULL DEFAULT 60,
    mute_permanent INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at REAL NOT NULL
)
"""

MODERATION_ACTIONS_DDL = """
CREATE TABLE IF NOT EXISTS moderation_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    channel_id INTEGER,
    user_id INTEGER,
    username TEXT,
    action TEXT NOT NULL,
    reason TEXT,
    duration_minutes INTEGER,
    message_id INTEGER,
    source TEXT NOT NULL DEFAULT 'auto',
    created_at REAL NOT NULL
)
"""

CHANNEL_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_channel_posts_channel_time ON channel_posts(channel_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_channel_comments_chat_time ON channel_comments(chat_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_channel_member_events_chat_time ON channel_member_events(chat_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_moderation_actions_chat_time ON moderation_actions(chat_id, created_at)",
)

# (column, sql_type, default_literal)
_RULES_EXTRA_COLS = (
    ("flood_max_messages", "INTEGER", "5"),
    ("flood_time_window_seconds", "INTEGER", "10"),
    ("flood_action", "TEXT", "'warn'"),
    ("warn_decay_hours", "INTEGER", "24"),
    ("instant_mute_on_warn", "INTEGER", "0"),
    ("instant_mute_duration_minutes", "INTEGER", "10"),
    ("allowed_urls_whitelist", "TEXT", "'[]'"),
)

_POSTS_EXTRA_COLS = (
    ("reactions_json", "TEXT", "'{}'"),
    ("full_text", "TEXT", "NULL"),
    ("post_url", "TEXT", "NULL"),
    ("discussion_chat_id", "INTEGER", "NULL"),
    ("discussion_message_id", "INTEGER", "NULL"),
)
_COMMENTS_EXTRA_COLS = (
    ("violation_kind", "TEXT", "NULL"),
    ("channel_post_message_id", "INTEGER", "NULL"),
)


def build_post_url(channel_id: int, message_id: int, username: str | None = None) -> str:
    """Public t.me link or private t.me/c/{id}/{message_id} form."""
    uname = (username or "").strip().lstrip("@")
    if uname:
        return f"https://t.me/{uname}/{int(message_id)}"
    cid = abs(int(channel_id))
    s = str(cid)
    if s.startswith("100") and len(s) > 3:
        s = s[3:]
    return f"https://t.me/c/{s}/{int(message_id)}"


def bot_db_path(bot_id: int) -> Path:
    return PROJECTS_DIR / f"bot_{bot_id}" / "user_data.db"


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: tuple[tuple[str, str, str], ...]) -> None:
    existing = {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, sql_type, default in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type} DEFAULT {default}")


def ensure_channel_hub_tables(conn: sqlite3.Connection) -> None:
    conn.execute(CHANNEL_REGISTRY_DDL)
    conn.execute(CHANNEL_POSTS_DDL)
    conn.execute(CHANNEL_COMMENTS_DDL)
    conn.execute(CHANNEL_MEMBER_EVENTS_DDL)
    conn.execute(USER_WARNINGS_DDL)
    conn.execute(MODERATION_RULES_DDL)
    conn.execute(MODERATION_ACTIONS_DDL)
    for ddl in CHANNEL_INDEXES:
        conn.execute(ddl)
    _ensure_columns(conn, "moderation_rules", _RULES_EXTRA_COLS)
    _ensure_columns(conn, "channel_posts", _POSTS_EXTRA_COLS)
    _ensure_columns(conn, "channel_comments", _COMMENTS_EXTRA_COLS)
    purge_spurious_channel_posts(conn)
    conn.commit()


def purge_spurious_channel_posts(conn: sqlite3.Connection) -> int:
    """Remove posts created from discussion reactions or foreign channel forwards."""
    cur1 = conn.execute(
        """
        DELETE FROM channel_posts WHERE channel_id IN (
            SELECT chat_id FROM channel_registry
            WHERE chat_type IN ('group', 'supergroup')
        )
        """
    )
    cur2 = conn.execute(
        """
        DELETE FROM channel_posts WHERE channel_id IN (
            SELECT chat_id FROM channel_registry
            WHERE chat_type = 'channel'
              AND IFNULL(username, '') = ''
              AND members_count IS NULL
        )
        """
    )
    return int(cur1.rowcount or 0) + int(cur2.rowcount or 0)


def connect_bot_db(bot_id: int) -> sqlite3.Connection:
    from backend.core.analytics_import import ensure_bot_user_db

    path = ensure_bot_user_db(bot_id)
    # timeout avoids multi-second freezes when another thread holds the DB
    conn = sqlite3.connect(str(path), timeout=8.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        pass
    ensure_channel_hub_tables(conn)
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return {k: row[k] for k in row.keys()}
    return dict(row) if isinstance(row, dict) else None


def default_rules_payload(channel_id: int = 0) -> dict[str, Any]:
    return {
        "channel_id": int(channel_id or 0),
        "forbidden_keywords": [],
        "allowed_urls_whitelist": [],
        "block_links": True,
        "block_stickers": False,
        "block_media": False,
        "anti_flood": False,
        "flood_max_messages": 5,
        "flood_time_window_seconds": 10,
        "flood_action": "warn",
        "warn_decay_hours": 24,
        "instant_mute_on_warn": False,
        "instant_mute_duration_minutes": 10,
        "max_warnings": 3,
        "mute_duration_minutes": 60,
        "mute_permanent": False,
        "enabled": True,
    }


def parse_keywords(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if not raw:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except (TypeError, ValueError):
            pass
        return [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
    return []


def normalize_url_host(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    raw = raw.replace("https://", "").replace("http://", "")
    raw = raw.split("/")[0].split("?")[0].strip(".")
    if raw.startswith("www."):
        raw = raw[4:]
    return raw


def parse_url_whitelist(raw: Any) -> list[str]:
    items = parse_keywords(raw)
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = (item or "").strip().lower()
        cleaned = cleaned.replace("https://", "").replace("http://", "")
        if cleaned.startswith("www."):
            cleaned = cleaned[4:]
        cleaned = cleaned.rstrip("/")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def url_host_allowed(url: str, whitelist: list[str]) -> bool:
    if not whitelist:
        return False
    url_l = (url or "").strip().lower()
    if not url_l:
        return True
    if "://" not in url_l:
        url_l = "https://" + url_l
    try:
        parsed = urlparse(url_l)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = (parsed.path or "").rstrip("/")
        for allowed in whitelist:
            a = (allowed or "").strip().lower().replace("https://", "").replace("http://", "").strip()
            if not a:
                continue
            if "/" in a:
                a_host, a_path = a.split("/", 1)
                a_host = normalize_url_host(a_host)
                a_path = "/" + a_path.strip("/")
                if (host == a_host or host.endswith("." + a_host)) and (
                    path == a_path.rstrip("/") or path.startswith(a_path)
                ):
                    return True
            else:
                a_host = normalize_url_host(a)
                if host == a_host or host.endswith("." + a_host):
                    return True
    except Exception:
        return False
    return False


def extract_urls_from_entities(text: str, entities: list[Any] | None) -> list[str]:
    """Extract real target URLs from Telegram entities (text_link / url)."""
    body = text or ""
    urls: list[str] = []
    for ent in entities or []:
        if isinstance(ent, dict):
            etype = str(ent.get("type") or "")
            offset = int(ent.get("offset") or 0)
            length = int(ent.get("length") or 0)
            ent_url = ent.get("url")
        else:
            etype = str(getattr(ent, "type", "") or getattr(getattr(ent, "type", None), "value", "") or "")
            if hasattr(etype, "value"):
                etype = str(etype.value)
            offset = int(getattr(ent, "offset", 0) or 0)
            length = int(getattr(ent, "length", 0) or 0)
            ent_url = getattr(ent, "url", None)
        etype = str(etype).lower()
        if etype in ("text_link", "textlink"):
            if ent_url:
                urls.append(str(ent_url))
        elif etype == "url":
            try:
                # Telegram offsets are UTF-16 code units
                utf16 = body.encode("utf-16-le")
                start = offset * 2
                end = (offset + length) * 2
                urls.append(utf16[start:end].decode("utf-16-le"))
            except Exception:
                urls.append(body[offset : offset + length])
    return [u for u in urls if u]


def get_moderation_rules(conn: sqlite3.Connection, channel_id: int = 0) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM moderation_rules WHERE channel_id = ? LIMIT 1",
        (int(channel_id),),
    ).fetchone()
    if not row and channel_id != 0:
        row = conn.execute(
            "SELECT * FROM moderation_rules WHERE channel_id = 0 LIMIT 1"
        ).fetchone()
    if not row:
        return default_rules_payload(channel_id)
    data = _row_to_dict(row) or default_rules_payload(channel_id)
    data["forbidden_keywords"] = parse_keywords(data.get("forbidden_keywords"))
    data["allowed_urls_whitelist"] = parse_url_whitelist(data.get("allowed_urls_whitelist"))
    for key in (
        "block_links",
        "block_stickers",
        "block_media",
        "anti_flood",
        "mute_permanent",
        "enabled",
        "instant_mute_on_warn",
    ):
        data[key] = bool(data.get(key))
    data["max_warnings"] = int(data.get("max_warnings") or 3)
    data["mute_duration_minutes"] = int(data.get("mute_duration_minutes") or 60)
    data["flood_max_messages"] = max(1, int(data.get("flood_max_messages") or 5))
    data["flood_time_window_seconds"] = max(1, int(data.get("flood_time_window_seconds") or 10))
    flood_action = str(data.get("flood_action") or "warn").strip().lower()
    if flood_action not in ("warn", "mute", "ban"):
        flood_action = "warn"
    data["flood_action"] = flood_action
    data["warn_decay_hours"] = max(0, int(data.get("warn_decay_hours") or 24))
    data["instant_mute_duration_minutes"] = max(1, int(data.get("instant_mute_duration_minutes") or 10))
    data["channel_id"] = int(data.get("channel_id") or 0)
    return data


def save_moderation_rules(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    channel_id = int(payload.get("channel_id") or 0)
    keywords = parse_keywords(payload.get("forbidden_keywords"))
    whitelist = parse_url_whitelist(payload.get("allowed_urls_whitelist"))
    flood_action = str(payload.get("flood_action") or "warn").strip().lower()
    if flood_action not in ("warn", "mute", "ban"):
        flood_action = "warn"
    now = time.time()
    conn.execute(
        """
        INSERT INTO moderation_rules (
            channel_id, forbidden_keywords, block_links, block_stickers, block_media,
            anti_flood, flood_max_messages, flood_time_window_seconds, flood_action,
            warn_decay_hours, instant_mute_on_warn, instant_mute_duration_minutes,
            allowed_urls_whitelist, max_warnings, mute_duration_minutes, mute_permanent,
            enabled, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            forbidden_keywords = excluded.forbidden_keywords,
            block_links = excluded.block_links,
            block_stickers = excluded.block_stickers,
            block_media = excluded.block_media,
            anti_flood = excluded.anti_flood,
            flood_max_messages = excluded.flood_max_messages,
            flood_time_window_seconds = excluded.flood_time_window_seconds,
            flood_action = excluded.flood_action,
            warn_decay_hours = excluded.warn_decay_hours,
            instant_mute_on_warn = excluded.instant_mute_on_warn,
            instant_mute_duration_minutes = excluded.instant_mute_duration_minutes,
            allowed_urls_whitelist = excluded.allowed_urls_whitelist,
            max_warnings = excluded.max_warnings,
            mute_duration_minutes = excluded.mute_duration_minutes,
            mute_permanent = excluded.mute_permanent,
            enabled = excluded.enabled,
            updated_at = excluded.updated_at
        """,
        (
            channel_id,
            json.dumps(keywords, ensure_ascii=False),
            1 if payload.get("block_links", True) else 0,
            1 if payload.get("block_stickers") else 0,
            1 if payload.get("block_media") else 0,
            1 if payload.get("anti_flood") else 0,
            max(1, int(payload.get("flood_max_messages") or 5)),
            max(1, int(payload.get("flood_time_window_seconds") or 10)),
            flood_action,
            max(0, int(payload.get("warn_decay_hours") or 24)),
            1 if payload.get("instant_mute_on_warn") else 0,
            max(1, int(payload.get("instant_mute_duration_minutes") or 10)),
            json.dumps(whitelist, ensure_ascii=False),
            max(1, int(payload.get("max_warnings") or 3)),
            max(0, int(payload.get("mute_duration_minutes") or 60)),
            1 if payload.get("mute_permanent") else 0,
            0 if payload.get("enabled") is False else 1,
            now,
        ),
    )
    conn.commit()
    return get_moderation_rules(conn, channel_id)


def list_channels(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM channel_registry ORDER BY updated_at DESC"
    ).fetchall()
    return [_row_to_dict(r) or {} for r in rows]


def apply_warning_decay(conn: sqlite3.Connection, rules: dict[str, Any], chat_id: int | None = None) -> int:
    """Clear or reduce warnings older than warn_decay_hours. Returns updated rows."""
    hours = int(rules.get("warn_decay_hours") or 0)
    if hours <= 0:
        return 0
    cutoff = time.time() - hours * 3600
    if chat_id is not None:
        cur = conn.execute(
            """UPDATE user_warnings SET warning_count = 0, reason = NULL
               WHERE chat_id = ? AND warning_count > 0
                 AND (last_warned_at IS NULL OR last_warned_at < ?)""",
            (int(chat_id), cutoff),
        )
    else:
        cur = conn.execute(
            """UPDATE user_warnings SET warning_count = 0, reason = NULL
               WHERE warning_count > 0
                 AND (last_warned_at IS NULL OR last_warned_at < ?)""",
            (cutoff,),
        )
    conn.commit()
    return int(cur.rowcount or 0)


def text_violates_rules(text: str, rules: dict[str, Any]) -> str | None:
    body = (text or "").strip()
    if not body:
        return None
    if rules.get("block_links") and URL_RE.search(body):
        whitelist = rules.get("allowed_urls_whitelist") or []
        # Soft path for plain text (no entities) — still check whitelist hosts
        matches = URL_RE.findall(body)
        # findall with groups returns tuples; use finditer
        blocked = False
        for m in URL_RE.finditer(body):
            if not url_host_allowed(m.group(0), whitelist):
                blocked = True
                break
        if blocked:
            return "Forbidden link"
    for kw in rules.get("forbidden_keywords") or []:
        if kw and kw.lower() in body.lower():
            return f"Forbidden phrase: {kw}"
    return None
