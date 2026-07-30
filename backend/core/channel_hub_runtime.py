"""Runtime helpers + aiogram handlers injected into generated bot main.py."""

from __future__ import annotations

CHANNEL_HUB_RUNTIME = r'''
# --- Channel Hub runtime ---
import re as _ch_re
import json as _ch_json
import time as _ch_time
from urllib.parse import urlparse as _ch_urlparse

_CH_URL_RE = _ch_re.compile(r"(?i)((https?://|www\.)\S+|t\.me/\S+|telegram\.me/\S+)")
_CH_FLOOD = {}


def _ch_ensure_tables():
    import sqlite3
    conn = sqlite3.connect(USER_DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS channel_registry (
        chat_id INTEGER PRIMARY KEY,
        title TEXT,
        chat_type TEXT,
        username TEXT,
        linked_chat_id INTEGER,
        members_count INTEGER,
        updated_at REAL NOT NULL
    );
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
    );
    CREATE TABLE IF NOT EXISTS channel_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        channel_id INTEGER,
        telegram_message_id INTEGER NOT NULL,
        user_id INTEGER,
        username TEXT,
        text TEXT,
        is_deleted INTEGER NOT NULL DEFAULT 0,
        moderated INTEGER NOT NULL DEFAULT 0,
        violation_kind TEXT,
        created_at REAL NOT NULL,
        UNIQUE(chat_id, telegram_message_id)
    );
    CREATE TABLE IF NOT EXISTS channel_member_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        user_id INTEGER,
        username TEXT,
        event_type TEXT NOT NULL,
        invite_link_used TEXT,
        timestamp REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS user_warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        username TEXT,
        warning_count INTEGER NOT NULL DEFAULT 0,
        reason TEXT,
        last_warned_at REAL,
        UNIQUE(chat_id, user_id)
    );
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
    );
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
    );
    """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(moderation_rules)").fetchall()}
    extras = [
        ("flood_max_messages", "INTEGER DEFAULT 5"),
        ("flood_time_window_seconds", "INTEGER DEFAULT 10"),
        ("flood_action", "TEXT DEFAULT 'warn'"),
        ("warn_decay_hours", "INTEGER DEFAULT 24"),
        ("instant_mute_on_warn", "INTEGER DEFAULT 0"),
        ("instant_mute_duration_minutes", "INTEGER DEFAULT 10"),
        ("allowed_urls_whitelist", "TEXT DEFAULT '[]'"),
    ]
    for name, decl in extras:
        if name not in cols:
            conn.execute(f"ALTER TABLE moderation_rules ADD COLUMN {name} {decl}")
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(channel_posts)").fetchall()}
    if "reactions_json" not in pcols:
        conn.execute("ALTER TABLE channel_posts ADD COLUMN reactions_json TEXT DEFAULT '{}'")
    if "full_text" not in pcols:
        conn.execute("ALTER TABLE channel_posts ADD COLUMN full_text TEXT")
    if "post_url" not in pcols:
        conn.execute("ALTER TABLE channel_posts ADD COLUMN post_url TEXT")
    if "discussion_chat_id" not in pcols:
        conn.execute("ALTER TABLE channel_posts ADD COLUMN discussion_chat_id INTEGER")
    if "discussion_message_id" not in pcols:
        conn.execute("ALTER TABLE channel_posts ADD COLUMN discussion_message_id INTEGER")
    ccols = {r[1] for r in conn.execute("PRAGMA table_info(channel_comments)").fetchall()}
    if "violation_kind" not in ccols:
        conn.execute("ALTER TABLE channel_comments ADD COLUMN violation_kind TEXT")
    if "channel_post_message_id" not in ccols:
        conn.execute("ALTER TABLE channel_comments ADD COLUMN channel_post_message_id INTEGER")
    conn.commit()
    conn.close()


def _ch_linked_channel_for_discussion(discussion_chat_id):
    """Return linked channel_id for a discussion group, if known."""
    import sqlite3
    try:
        _ch_ensure_tables()
        conn = sqlite3.connect(USER_DB_PATH)
        row = conn.execute(
            "SELECT linked_chat_id FROM channel_registry WHERE chat_id = ? LIMIT 1",
            (int(discussion_chat_id),),
        ).fetchone()
        if row and row[0] is not None:
            conn.close()
            return int(row[0])
        row = conn.execute(
            "SELECT chat_id FROM channel_registry WHERE linked_chat_id = ? AND chat_type = 'channel' LIMIT 1",
            (int(discussion_chat_id),),
        ).fetchone()
        conn.close()
        return int(row[0]) if row else None
    except Exception:
        return None


def _ch_purge_spurious_posts(conn=None):
    """Drop fake posts created from discussion reactions / foreign forwards."""
    import sqlite3
    owns = conn is not None
    if not owns:
        _ch_ensure_tables()
        conn = sqlite3.connect(USER_DB_PATH)
    try:
        conn.execute(
            """
            DELETE FROM channel_posts WHERE channel_id IN (
                SELECT chat_id FROM channel_registry
                WHERE chat_type IN ('group', 'supergroup')
            )
            """
        )
        # Channels only seen via foreign forwards (no public username, never counted members).
        conn.execute(
            """
            DELETE FROM channel_posts WHERE channel_id IN (
                SELECT chat_id FROM channel_registry
                WHERE chat_type = 'channel'
                  AND IFNULL(username, '') = ''
                  AND members_count IS NULL
            )
            """
        )
        if not owns:
            conn.commit()
    finally:
        if not owns:
            conn.close()


def _ch_build_post_url(channel_id, message_id, username=None):
    uname = (username or "").strip().lstrip("@")
    if uname:
        return f"https://t.me/{uname}/{int(message_id)}"
    cid = abs(int(channel_id))
    s = str(cid)
    if s.startswith("100") and len(s) > 3:
        s = s[3:]
    return f"https://t.me/c/{s}/{int(message_id)}"


def _ch_lookup_channel_username(channel_id):
    import sqlite3
    try:
        conn = sqlite3.connect(USER_DB_PATH)
        row = conn.execute(
            "SELECT username FROM channel_registry WHERE chat_id = ? LIMIT 1",
            (int(channel_id),),
        ).fetchone()
        conn.close()
        return (row[0] if row else "") or ""
    except Exception:
        return ""


def _ch_norm_host(value):
    raw = (value or "").strip().lower().replace("https://", "").replace("http://", "")
    raw = raw.split("/")[0].split("?")[0].strip(".")
    if raw.startswith("www."):
        raw = raw[4:]
    return raw


def _ch_url_allowed(url, whitelist):
    if not whitelist:
        return False
    url_l = (url or "").strip().lower()
    if not url_l:
        return True
    if "://" not in url_l:
        url_l = "https://" + url_l
    try:
        parsed = _ch_urlparse(url_l)
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
                a_host = _ch_norm_host(a_host)
                a_path = "/" + a_path.strip("/")
                if (host == a_host or host.endswith("." + a_host)) and (
                    path == a_path.rstrip("/") or path.startswith(a_path)
                ):
                    return True
            else:
                a_host = _ch_norm_host(a)
                if host == a_host or host.endswith("." + a_host):
                    return True
    except Exception:
        return False
    return False


def _ch_entity_urls(message):
    text = message.text or message.caption or ""
    entities = list(getattr(message, "entities", None) or []) + list(getattr(message, "caption_entities", None) or [])
    urls = []
    for ent in entities:
        etype = getattr(ent, "type", None)
        etype = getattr(etype, "value", etype)
        etype = str(etype or "").lower()
        if etype in ("text_link", "textlink"):
            if getattr(ent, "url", None):
                urls.append(str(ent.url))
        elif etype == "url":
            try:
                offset = int(getattr(ent, "offset", 0) or 0)
                length = int(getattr(ent, "length", 0) or 0)
                utf16 = text.encode("utf-16-le")
                chunk = utf16[offset * 2:(offset + length) * 2].decode("utf-16-le")
                urls.append(chunk)
            except Exception:
                pass
    return urls


def _ch_upsert_chat(chat, members_count=None, linked_chat_id=None):
    if not chat:
        return
    import sqlite3
    _ch_ensure_tables()
    conn = sqlite3.connect(USER_DB_PATH)
    conn.execute(
        """
        INSERT INTO channel_registry (chat_id, title, chat_type, username, linked_chat_id, members_count, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            title = excluded.title,
            chat_type = excluded.chat_type,
            username = excluded.username,
            linked_chat_id = COALESCE(excluded.linked_chat_id, channel_registry.linked_chat_id),
            members_count = COALESCE(excluded.members_count, channel_registry.members_count),
            updated_at = excluded.updated_at
        """,
        (
            int(chat.id),
            getattr(chat, "title", None) or "",
            str(getattr(chat, "type", "") or ""),
            getattr(chat, "username", None) or "",
            linked_chat_id,
            members_count,
            _ch_time.time(),
        ),
    )
    conn.commit()
    conn.close()


def _ch_get_rules(channel_id=0):
    import sqlite3
    _ch_ensure_tables()
    conn = sqlite3.connect(USER_DB_PATH)
    row = conn.execute("SELECT * FROM moderation_rules WHERE channel_id = ? LIMIT 1", (int(channel_id or 0),)).fetchone()
    if not row:
        row = conn.execute("SELECT * FROM moderation_rules WHERE channel_id = 0 LIMIT 1").fetchone()
    cols = [d[0] for d in conn.execute("PRAGMA table_info(moderation_rules)").fetchall()]
    conn.close()
    if not row:
        return {
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
    data = dict(zip(cols, row))
    def _list(raw):
        try:
            val = _ch_json.loads(raw or "[]")
            return [str(x).strip() for x in val if str(x).strip()] if isinstance(val, list) else []
        except Exception:
            return []
    flood_action = str(data.get("flood_action") or "warn").lower()
    if flood_action not in ("warn", "mute", "ban"):
        flood_action = "warn"
    return {
        "forbidden_keywords": _list(data.get("forbidden_keywords")),
        "allowed_urls_whitelist": [_ch_norm_host(x) if "/" not in str(x) else str(x).replace("https://", "").replace("http://", "") for x in _list(data.get("allowed_urls_whitelist"))],
        "block_links": bool(data.get("block_links")),
        "block_stickers": bool(data.get("block_stickers")),
        "block_media": bool(data.get("block_media")),
        "anti_flood": bool(data.get("anti_flood")),
        "flood_max_messages": int(data.get("flood_max_messages") or 5),
        "flood_time_window_seconds": int(data.get("flood_time_window_seconds") or 10),
        "flood_action": flood_action,
        "warn_decay_hours": int(data.get("warn_decay_hours") or 24),
        "instant_mute_on_warn": bool(data.get("instant_mute_on_warn")),
        "instant_mute_duration_minutes": int(data.get("instant_mute_duration_minutes") or 10),
        "max_warnings": int(data.get("max_warnings") or 3),
        "mute_duration_minutes": int(data.get("mute_duration_minutes") or 60),
        "mute_permanent": bool(data.get("mute_permanent")),
        "enabled": bool(data.get("enabled", 1)),
    }


def _ch_reactions_payload(message):
    reactions = {}
    total = 0
    try:
        react = getattr(message, "reactions", None)
        items = getattr(react, "reactions", None) if react else None
        if items:
            for r in items:
                count = int(getattr(r, "total_count", 0) or getattr(r, "total_count", 0) or 0)
                total += count
                emoji = None
                rtype = getattr(r, "type", None)
                if rtype is not None:
                    emoji = getattr(rtype, "emoji", None)
                    if not emoji:
                        custom = getattr(rtype, "custom_emoji_id", None)
                        emoji = f"custom:{custom}" if custom else str(getattr(rtype, "type", "reaction"))
                reactions[str(emoji or "?")] = reactions.get(str(emoji or "?"), 0) + count
    except Exception:
        reactions = {}
        total = 0
    return total, reactions


def _ch_message_views(message):
    """Extract views from channel_post / edited_channel_post payloads only.

    Bot API historically sent ``views`` on channel posts; group ``message`` updates
    never include it. Current Bot API docs omit ``views`` entirely — if Telegram
    still sends it, it lands in pydantic ``model_extra`` (aiogram Message has no field).
    """
    if message is None:
        return None
    chat = getattr(message, "chat", None)
    chat_type = str(getattr(chat, "type", "") or "") if chat is not None else ""
    # Never treat discussion/group messages as a source of view counters.
    if chat_type in ("group", "supergroup", "private"):
        return None
    candidates = []
    for src in (
        getattr(message, "views", None),
        (getattr(message, "model_extra", None) or {}).get("views")
        if isinstance(getattr(message, "model_extra", None), dict)
        else None,
    ):
        candidates.append(src)
    try:
        extra = getattr(message, "__pydantic_extra__", None)
        if isinstance(extra, dict):
            candidates.append(extra.get("views"))
    except Exception:
        pass
    try:
        data = message.model_dump(exclude_none=False)
        candidates.append(data.get("views"))
        nested = data.get("__pydantic_extra__") or {}
        if isinstance(nested, dict):
            candidates.append(nested.get("views"))
    except Exception:
        pass
    for src in candidates:
        if src is None:
            continue
        try:
            return int(src)
        except Exception:
            continue
    return None


def _ch_log_channel_post_views(message, views):
    try:
        extra = getattr(message, "model_extra", None) or {}
        extra_keys = sorted(extra.keys()) if isinstance(extra, dict) else []
        log.info(
            "Channel Hub channel_post mid=%s chat=%s views=%s model_extra_keys=%s",
            getattr(message, "message_id", None),
            getattr(getattr(message, "chat", None), "id", None),
            views,
            extra_keys,
        )
    except Exception:
        pass


def _ch_origin_channel_ref(message):
    """Return (channel_id, channel_post_message_id, username) from a forwarded/auto-forward message."""
    if not message:
        return None, None, ""
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        chat = getattr(origin, "chat", None)
        if chat is not None and str(getattr(chat, "type", "") or "") == "channel":
            mid = int(getattr(origin, "message_id", 0) or 0)
            if mid:
                return int(chat.id), mid, (getattr(chat, "username", None) or "")
    src = getattr(message, "forward_from_chat", None)
    if src is not None and str(getattr(src, "type", "") or "") == "channel":
        mid = int(getattr(message, "forward_from_message_id", 0) or 0)
        if mid:
            return int(src.id), mid, (getattr(src, "username", None) or "")
    return None, None, ""


def _ch_resolve_comment_post_ref(message):
    """Map a discussion comment to (channel_id, channel_post_message_id)."""
    import sqlite3
    channel_id = None
    post_mid = None

    reply = getattr(message, "reply_to_message", None)
    if reply is not None:
        channel_id, post_mid, _ = _ch_origin_channel_ref(reply)
        if not channel_id:
            sender = getattr(reply, "sender_chat", None)
            if sender is not None and str(getattr(sender, "type", "") or "") == "channel":
                channel_id = int(sender.id)
                # Prefer origin message id; discussion message_id is NOT the channel post id.
                _, origin_mid, _ = _ch_origin_channel_ref(reply)
                post_mid = origin_mid

    external = getattr(message, "external_reply", None)
    if (not channel_id or not post_mid) and external is not None:
        chat = getattr(external, "chat", None)
        if chat is not None and str(getattr(chat, "type", "") or "") == "channel":
            channel_id = int(chat.id)
            mid = int(getattr(external, "message_id", 0) or 0)
            if mid:
                post_mid = mid
        origin = getattr(external, "origin", None)
        if origin is not None and (not channel_id or not post_mid):
            chat = getattr(origin, "chat", None)
            if chat is not None and str(getattr(chat, "type", "") or "") == "channel":
                mid = int(getattr(origin, "message_id", 0) or 0)
                if mid:
                    channel_id, post_mid = int(chat.id), mid

    # Reply to another comment: inherit parent comment's post ref from DB.
    if (not channel_id or not post_mid) and reply is not None and getattr(message, "chat", None):
        try:
            _ch_ensure_tables()
            conn = sqlite3.connect(USER_DB_PATH)
            row = conn.execute(
                """
                SELECT channel_id, channel_post_message_id FROM channel_comments
                WHERE chat_id = ? AND telegram_message_id = ? LIMIT 1
                """,
                (int(message.chat.id), int(reply.message_id)),
            ).fetchone()
            conn.close()
            if row:
                if not channel_id and row[0] is not None:
                    channel_id = int(row[0])
                if not post_mid and row[1] is not None:
                    post_mid = int(row[1])
        except Exception:
            pass

    # Fallback: linked channel from registry + sole post in that channel.
    if getattr(message, "chat", None):
        try:
            _ch_ensure_tables()
            conn = sqlite3.connect(USER_DB_PATH)
            if not channel_id:
                row = conn.execute(
                    "SELECT linked_chat_id FROM channel_registry WHERE chat_id = ? LIMIT 1",
                    (int(message.chat.id),),
                ).fetchone()
                if row and row[0] is not None:
                    channel_id = int(row[0])
                else:
                    row = conn.execute(
                        "SELECT chat_id FROM channel_registry WHERE linked_chat_id = ? AND chat_type = 'channel' LIMIT 1",
                        (int(message.chat.id),),
                    ).fetchone()
                    if row:
                        channel_id = int(row[0])
            if channel_id and not post_mid:
                rows = conn.execute(
                    "SELECT telegram_message_id FROM channel_posts WHERE channel_id = ? ORDER BY created_at DESC LIMIT 2",
                    (int(channel_id),),
                ).fetchall()
                if len(rows) == 1:
                    post_mid = int(rows[0][0])
            conn.close()
        except Exception:
            pass

    return channel_id, post_mid


def _ch_recount_post_comments(conn, channel_id, post_message_id):
    if not channel_id or not post_message_id:
        return
    conn.execute(
        """
        UPDATE channel_posts
        SET comments_count = (
            SELECT COUNT(*) FROM channel_comments c
            WHERE c.channel_id = ? AND c.channel_post_message_id = ? AND c.is_deleted = 0
        )
        WHERE channel_id = ? AND telegram_message_id = ?
        """,
        (int(channel_id), int(post_message_id), int(channel_id), int(post_message_id)),
    )


def _ch_upsert_post_stats(
    channel_id,
    telegram_message_id,
    text="",
    views=0,
    reactions_total=0,
    reactions_map=None,
    created=None,
    username=None,
    discussion_chat_id=None,
    discussion_message_id=None,
    allow_insert=True,
):
    import sqlite3
    _ch_ensure_tables()
    if created is None:
        created = _ch_time.time()
    reactions_map = reactions_map or {}
    full_text = (text or "")[:8000]
    uname = username if username is not None else _ch_lookup_channel_username(channel_id)
    post_url = _ch_build_post_url(channel_id, telegram_message_id, uname)
    conn = sqlite3.connect(USER_DB_PATH)
    existing = conn.execute(
        """SELECT id FROM channel_posts
           WHERE channel_id = ? AND telegram_message_id = ? LIMIT 1""",
        (int(channel_id), int(telegram_message_id)),
    ).fetchone()
    if not existing and not allow_insert:
        conn.close()
        return False
    conn.execute(
        """
        INSERT INTO channel_posts
        (channel_id, telegram_message_id, text, full_text, post_url, views_count, forwards_count, comments_count, reactions_count, reactions_json, created_at, discussion_chat_id, discussion_message_id)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?)
        ON CONFLICT(channel_id, telegram_message_id) DO UPDATE SET
            text = CASE WHEN excluded.text != '' THEN excluded.text ELSE channel_posts.text END,
            full_text = CASE WHEN excluded.full_text != '' THEN excluded.full_text ELSE COALESCE(channel_posts.full_text, channel_posts.text) END,
            post_url = COALESCE(excluded.post_url, channel_posts.post_url),
            views_count = CASE WHEN excluded.views_count > channel_posts.views_count THEN excluded.views_count ELSE channel_posts.views_count END,
            reactions_count = CASE WHEN excluded.reactions_count > channel_posts.reactions_count THEN excluded.reactions_count ELSE channel_posts.reactions_count END,
            reactions_json = CASE WHEN length(excluded.reactions_json) > 2 THEN excluded.reactions_json ELSE channel_posts.reactions_json END,
            discussion_chat_id = COALESCE(excluded.discussion_chat_id, channel_posts.discussion_chat_id),
            discussion_message_id = COALESCE(excluded.discussion_message_id, channel_posts.discussion_message_id)
        """,
        (
            int(channel_id),
            int(telegram_message_id),
            full_text[:4000],
            full_text,
            post_url,
            int(views or 0),
            int(reactions_total or 0),
            _ch_json.dumps(reactions_map, ensure_ascii=False),
            float(created),
            int(discussion_chat_id) if discussion_chat_id else None,
            int(discussion_message_id) if discussion_message_id else None,
        ),
    )
    conn.commit()
    conn.close()
    return True


def _ch_save_post(message):
    if not message or not message.chat:
        return
    # Only real channel posts belong in channel_posts.
    if str(getattr(message.chat, "type", "") or "") != "channel":
        return
    text = message.text or message.caption or ""
    views = _ch_message_views(message)
    _ch_log_channel_post_views(message, views)
    reactions, reactions_map = _ch_reactions_payload(message)
    created = float(message.date.timestamp()) if getattr(message, "date", None) else _ch_time.time()
    username = getattr(message.chat, "username", None) or ""
    _ch_upsert_post_stats(
        int(message.chat.id),
        int(message.message_id),
        text=text,
        views=int(views or 0),
        reactions_total=reactions,
        reactions_map=reactions_map,
        created=created,
        username=username,
        allow_insert=True,
    )
    _ch_upsert_chat(message.chat)


def _ch_save_auto_forward_post(message):
    """Discussion auto-forward: link discussion copy to channel post; never invent foreign posts."""
    if not message or not message.chat:
        return False
    if not getattr(message, "is_automatic_forward", False):
        return False
    channel_id, telegram_message_id, username = _ch_origin_channel_ref(message)
    if not channel_id or not telegram_message_id:
        return False
    linked = _ch_linked_channel_for_discussion(int(message.chat.id))
    # Manual forwards from other channels must not create analytics posts.
    if linked is not None and int(linked) != int(channel_id):
        return False
    if linked is None:
        # First auto-forward: remember discussion ↔ channel link.
        _ch_upsert_chat(message.chat, linked_chat_id=int(channel_id))
    text = message.text or message.caption or ""
    reactions, reactions_map = _ch_reactions_payload(message)
    created = float(message.date.timestamp()) if getattr(message, "date", None) else _ch_time.time()
    # Update existing channel post only (created by channel_post). Still set discussion bridge.
    ok = _ch_upsert_post_stats(
        channel_id,
        telegram_message_id,
        text=text,
        views=0,
        reactions_total=reactions,
        reactions_map=reactions_map,
        created=created,
        username=username,
        discussion_chat_id=int(message.chat.id),
        discussion_message_id=int(message.message_id),
        allow_insert=False,
    )
    if not ok:
        # Channel post not saved yet — insert once with bridge so later reactions map correctly.
        _ch_upsert_post_stats(
            channel_id,
            telegram_message_id,
            text=text,
            views=0,
            reactions_total=reactions,
            reactions_map=reactions_map,
            created=created,
            username=username,
            discussion_chat_id=int(message.chat.id),
            discussion_message_id=int(message.message_id),
            allow_insert=True,
        )
    chat = None
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        chat = getattr(origin, "chat", None)
    if chat is not None and str(getattr(chat, "type", "") or "") == "channel":
        _ch_upsert_chat(chat)
    _ch_upsert_chat(message.chat, linked_chat_id=int(channel_id))
    return True


def _ch_apply_reaction_counts(chat_id, message_id, reaction_list, chat_type=None):
    """Update reactions on an existing channel post only — never create posts from reactions."""
    import sqlite3
    reactions = {}
    total = 0
    for r in reaction_list or []:
        try:
            count = int(getattr(r, "total_count", 0) or 0)
            total += count
            rtype = getattr(r, "type", None)
            emoji = getattr(rtype, "emoji", None) if rtype is not None else None
            if not emoji and rtype is not None:
                custom = getattr(rtype, "custom_emoji_id", None)
                emoji = f"custom:{custom}" if custom else "?"
            key = str(emoji or "?")
            reactions[key] = reactions.get(key, 0) + count
        except Exception:
            continue
    _ch_ensure_tables()
    _ch_purge_spurious_posts()
    conn = sqlite3.connect(USER_DB_PATH)
    target_channel_id = int(chat_id)
    target_message_id = int(message_id)
    ctype = str(chat_type or "")

    if ctype in ("group", "supergroup"):
        linked = _ch_linked_channel_for_discussion(int(chat_id))
        row = conn.execute(
            """
            SELECT channel_id, telegram_message_id FROM channel_posts
            WHERE discussion_chat_id = ? AND discussion_message_id = ?
            LIMIT 1
            """,
            (int(chat_id), int(message_id)),
        ).fetchone()
        if row:
            target_channel_id, target_message_id = int(row[0]), int(row[1])
        elif linked is not None:
            # Fallback: only if exactly one recent unmatched post — avoid wrong mapping.
            row = conn.execute(
                """
                SELECT channel_id, telegram_message_id FROM channel_posts
                WHERE channel_id = ? AND discussion_message_id IS NULL
                ORDER BY created_at DESC LIMIT 2
                """,
                (int(linked),),
            ).fetchall()
            if len(row) == 1:
                target_channel_id, target_message_id = int(row[0][0]), int(row[0][1])
                conn.execute(
                    """UPDATE channel_posts
                       SET discussion_chat_id = ?, discussion_message_id = ?
                       WHERE channel_id = ? AND telegram_message_id = ?""",
                    (int(chat_id), int(message_id), target_channel_id, target_message_id),
                )
            else:
                conn.close()
                return
        else:
            conn.close()
            return
    elif ctype and ctype != "channel":
        conn.close()
        return

    cur = conn.execute(
        """UPDATE channel_posts
           SET reactions_count = ?, reactions_json = ?
           WHERE channel_id = ? AND telegram_message_id = ?""",
        (int(total), _ch_json.dumps(reactions, ensure_ascii=False), target_channel_id, target_message_id),
    )
    # Do not INSERT — unknown ids are discussion copies / foreign forwards.
    conn.commit()
    conn.close()
    return cur.rowcount


def _ch_save_comment(message, moderated=0, deleted=0, violation_kind=None):
    import sqlite3
    if not message or not message.chat or not message.from_user:
        return
    _ch_ensure_tables()
    text = (message.text or message.caption or "")[:4000]
    username = message.from_user.username or message.from_user.full_name or str(message.from_user.id)
    created = float(message.date.timestamp()) if getattr(message, "date", None) else _ch_time.time()
    channel_id, channel_post_message_id = _ch_resolve_comment_post_ref(message)
    conn = sqlite3.connect(USER_DB_PATH)
    conn.execute(
        """
        INSERT INTO channel_comments
        (chat_id, channel_id, channel_post_message_id, telegram_message_id, user_id, username, text, is_deleted, moderated, violation_kind, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, telegram_message_id) DO UPDATE SET
            text = excluded.text,
            channel_id = COALESCE(excluded.channel_id, channel_comments.channel_id),
            channel_post_message_id = COALESCE(excluded.channel_post_message_id, channel_comments.channel_post_message_id),
            is_deleted = CASE WHEN excluded.is_deleted > channel_comments.is_deleted THEN excluded.is_deleted ELSE channel_comments.is_deleted END,
            moderated = CASE WHEN excluded.moderated > channel_comments.moderated THEN excluded.moderated ELSE channel_comments.moderated END,
            violation_kind = COALESCE(excluded.violation_kind, channel_comments.violation_kind)
        """,
        (
            int(message.chat.id),
            channel_id,
            channel_post_message_id,
            int(message.message_id),
            int(message.from_user.id),
            username,
            text,
            int(deleted),
            int(moderated),
            violation_kind,
            created,
        ),
    )
    if channel_id and channel_post_message_id:
        _ch_recount_post_comments(conn, channel_id, channel_post_message_id)
    elif channel_id:
        # Soft recount by channel when post id still unknown (single-post channels).
        rows = conn.execute(
            "SELECT telegram_message_id FROM channel_posts WHERE channel_id = ? LIMIT 2",
            (int(channel_id),),
        ).fetchall()
        if len(rows) == 1:
            conn.execute(
                """UPDATE channel_comments SET channel_post_message_id = ?
                   WHERE chat_id = ? AND telegram_message_id = ?""",
                (int(rows[0][0]), int(message.chat.id), int(message.message_id)),
            )
            _ch_recount_post_comments(conn, channel_id, int(rows[0][0]))
    conn.commit()
    conn.close()
    _ch_upsert_chat(message.chat, linked_chat_id=channel_id)


def _ch_log_action(chat_id, user_id, username, action, reason, duration_minutes=None, message_id=None, channel_id=None):
    import sqlite3
    _ch_ensure_tables()
    conn = sqlite3.connect(USER_DB_PATH)
    conn.execute(
        """
        INSERT INTO moderation_actions
        (chat_id, channel_id, user_id, username, action, reason, duration_minutes, message_id, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'auto', ?)
        """,
        (int(chat_id), channel_id, int(user_id) if user_id else None, username, action, reason, duration_minutes, message_id, _ch_time.time()),
    )
    conn.commit()
    conn.close()


def _ch_apply_warn_decay(chat_id, user_id, rules):
    import sqlite3
    hours = int(rules.get("warn_decay_hours") or 0)
    if hours <= 0:
        return
    cutoff = _ch_time.time() - hours * 3600
    conn = sqlite3.connect(USER_DB_PATH)
    conn.execute(
        """UPDATE user_warnings SET warning_count = 0, reason = NULL
           WHERE chat_id = ? AND user_id = ? AND warning_count > 0
             AND (last_warned_at IS NULL OR last_warned_at < ?)""",
        (int(chat_id), int(user_id), cutoff),
    )
    conn.commit()
    conn.close()


def _ch_bump_warning(chat_id, user_id, username, reason):
    import sqlite3
    _ch_ensure_tables()
    conn = sqlite3.connect(USER_DB_PATH)
    row = conn.execute(
        "SELECT warning_count FROM user_warnings WHERE chat_id = ? AND user_id = ?",
        (int(chat_id), int(user_id)),
    ).fetchone()
    count = int(row[0] if row else 0) + 1
    conn.execute(
        """
        INSERT INTO user_warnings (chat_id, user_id, username, warning_count, reason, last_warned_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            username = excluded.username,
            warning_count = excluded.warning_count,
            reason = excluded.reason,
            last_warned_at = excluded.last_warned_at
        """,
        (int(chat_id), int(user_id), username, count, reason, _ch_time.time()),
    )
    conn.commit()
    conn.close()
    return count


def _ch_reset_warnings(chat_id, user_id):
    import sqlite3
    conn = sqlite3.connect(USER_DB_PATH)
    conn.execute(
        "UPDATE user_warnings SET warning_count = 0 WHERE chat_id = ? AND user_id = ?",
        (int(chat_id), int(user_id)),
    )
    conn.commit()
    conn.close()


def _ch_violation(message, rules):
    """Return (reason, kind) or (None, None). kind: link|flood|keyword|sticker|media"""
    if not rules.get("enabled", True):
        return None, None
    text = message.text or message.caption or ""
    if rules.get("block_links"):
        whitelist = rules.get("allowed_urls_whitelist") or []
        entity_urls = _ch_entity_urls(message)
        for url in entity_urls:
            if not _ch_url_allowed(url, whitelist):
                return "Forbidden link (entity)", "link"
        # Visible raw URLs without entity still blocked unless whitelisted
        for m in _CH_URL_RE.finditer(text or ""):
            if not _ch_url_allowed(m.group(0), whitelist):
                return "Forbidden link", "link"
    for kw in rules.get("forbidden_keywords") or []:
        if kw and text and kw.lower() in text.lower():
            return f"Forbidden phrase: {kw}", "keyword"
    if rules.get("block_stickers") and getattr(message, "sticker", None):
        return "Stickers are blocked", "sticker"
    if rules.get("block_media") and (
        getattr(message, "photo", None)
        or getattr(message, "video", None)
        or getattr(message, "animation", None)
        or getattr(message, "document", None)
    ):
        return "Media is blocked", "media"
    if rules.get("anti_flood") and message.from_user:
        key = (int(message.chat.id), int(message.from_user.id))
        now = _ch_time.time()
        window = max(1, int(rules.get("flood_time_window_seconds") or 10))
        limit = max(1, int(rules.get("flood_max_messages") or 5))
        bucket = _CH_FLOOD.get(key) or []
        bucket = [t for t in bucket if now - t < window]
        bucket.append(now)
        _CH_FLOOD[key] = bucket
        if len(bucket) >= limit:
            return "Anti-flood", "flood"
    return None, None


async def _ch_restrict(bot, chat_id, user_id, minutes, reason, action="mute"):
    from aiogram.types import ChatPermissions
    if action == "ban":
        try:
            await bot.ban_chat_member(chat_id, user_id)
            _ch_log_action(chat_id, user_id, str(user_id), "ban", reason)
        except Exception as exc:
            log.warning("Channel Hub ban failed: %s", exc)
        _ch_reset_warnings(chat_id, user_id)
        return
    until = None if minutes <= 0 else int(_ch_time.time()) + int(minutes) * 60
    try:
        await bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        _ch_log_action(chat_id, user_id, str(user_id), "mute", reason, duration_minutes=minutes)
    except Exception as exc:
        log.warning("Channel Hub mute failed: %s", exc)


async def _ch_mute_or_ban(bot, chat_id, user_id, rules, reason):
    if rules.get("mute_permanent"):
        await _ch_restrict(bot, chat_id, user_id, 0, reason, action="ban")
        return
    minutes = int(rules.get("mute_duration_minutes") or 60)
    await _ch_restrict(bot, chat_id, user_id, minutes, reason, action="mute")
    _ch_reset_warnings(chat_id, user_id)


@dp.channel_post()
async def on_channel_hub_post(message: types.Message):
    try:
        _ch_save_post(message)
        try:
            count = await bot.get_chat_member_count(message.chat.id)
            _ch_upsert_chat(message.chat, members_count=count)
        except Exception:
            pass
    except Exception as exc:
        log.warning("Channel Hub post save failed: %s", exc)


@dp.edited_channel_post()
async def on_channel_hub_edited_post(message: types.Message):
    try:
        _ch_save_post(message)
    except Exception as exc:
        log.warning("Channel Hub edited post failed: %s", exc)


@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def on_channel_hub_group_message(message: types.Message):
    try:
        if getattr(message, "is_automatic_forward", False):
            try:
                _ch_save_auto_forward_post(message)
            except Exception as exc:
                log.warning("Channel Hub auto-forward stats failed: %s", exc)
    except Exception:
        pass
    if not message.from_user or message.from_user.is_bot:
        return
    if getattr(message, "is_automatic_forward", False):
        return
    try:
        rules = _ch_get_rules(0)
        _ch_apply_warn_decay(message.chat.id, message.from_user.id, rules)
        reason, kind = _ch_violation(message, rules)
        if reason:
            try:
                await message.delete()
            except Exception:
                pass
            _ch_save_comment(message, moderated=1, deleted=1, violation_kind=kind)
            username = message.from_user.username or message.from_user.full_name or str(message.from_user.id)
            flood_action = str(rules.get("flood_action") or "warn")
            if kind == "flood" and flood_action in ("mute", "ban"):
                await _ch_restrict(
                    bot,
                    message.chat.id,
                    message.from_user.id,
                    int(rules.get("mute_duration_minutes") or 60) if flood_action == "mute" else 0,
                    reason,
                    action=flood_action,
                )
                _ch_log_action(message.chat.id, message.from_user.id, username, flood_action, reason, message_id=message.message_id)
                return
            count = _ch_bump_warning(message.chat.id, message.from_user.id, username, reason)
            max_w = int(rules.get("max_warnings") or 3)
            _ch_log_action(
                message.chat.id,
                message.from_user.id,
                username,
                "warn",
                reason,
                message_id=message.message_id,
            )
            if rules.get("instant_mute_on_warn"):
                await _ch_restrict(
                    bot,
                    message.chat.id,
                    message.from_user.id,
                    int(rules.get("instant_mute_duration_minutes") or 10),
                    "Instant mute on warn",
                    action="mute",
                )
            try:
                notice = await message.answer(
                    f"@{username} Предупреждение ({count}/{max_w}). Причина: {reason}."
                )
                async def _drop_notice(msg_id=notice.message_id, chat_id=message.chat.id):
                    await asyncio.sleep(20)
                    try:
                        await bot.delete_message(chat_id, msg_id)
                    except Exception:
                        pass
                asyncio.create_task(_drop_notice())
            except Exception:
                pass
            if count >= max_w:
                await _ch_mute_or_ban(bot, message.chat.id, message.from_user.id, rules, "Max warnings reached")
            return
        _ch_save_comment(message, violation_kind="clean")
        _ch_upsert_chat(message.chat)
    except Exception as exc:
        log.warning("Channel Hub group moderation failed: %s", exc)


@dp.message_reaction_count()
async def on_channel_hub_reaction_count(event: types.MessageReactionCountUpdated):
    try:
        chat = event.chat
        _ch_apply_reaction_counts(
            int(chat.id),
            int(event.message_id),
            event.reactions,
            chat_type=str(getattr(chat, "type", "") or ""),
        )
        _ch_upsert_chat(event.chat)
    except Exception as exc:
        log.warning("Channel Hub reaction count failed: %s", exc)


@dp.chat_member()
async def on_channel_hub_chat_member(event: types.ChatMemberUpdated):
    try:
        _ch_ensure_tables()
        old = event.old_chat_member.status if event.old_chat_member else ""
        new = event.new_chat_member.status if event.new_chat_member else ""
        user = event.new_chat_member.user if event.new_chat_member else None
        if not user:
            return
        event_type = None
        if old in ("left", "kicked") and new in ("member", "administrator", "restricted", "creator"):
            event_type = "join"
        elif old in ("member", "administrator", "restricted", "creator") and new in ("left", "kicked"):
            event_type = "leave"
        if not event_type:
            return
        invite = None
        try:
            if event.invite_link:
                invite = getattr(event.invite_link, "invite_link", None) or str(event.invite_link)
        except Exception:
            invite = None
        import sqlite3
        conn = sqlite3.connect(USER_DB_PATH)
        conn.execute(
            """
            INSERT INTO channel_member_events
            (chat_id, user_id, username, event_type, invite_link_used, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(event.chat.id),
                int(user.id),
                user.username or user.full_name or str(user.id),
                event_type,
                invite,
                _ch_time.time(),
            ),
        )
        conn.commit()
        conn.close()
        _ch_upsert_chat(event.chat)
        try:
            count = await bot.get_chat_member_count(event.chat.id)
            _ch_upsert_chat(event.chat, members_count=count)
        except Exception:
            pass
    except Exception as exc:
        log.warning("Channel Hub chat_member failed: %s", exc)


@dp.my_chat_member()
async def on_channel_hub_my_chat_member(event: types.ChatMemberUpdated):
    try:
        _ch_upsert_chat(event.chat)
        try:
            count = await bot.get_chat_member_count(event.chat.id)
            _ch_upsert_chat(event.chat, members_count=count)
        except Exception:
            pass
    except Exception as exc:
        log.warning("Channel Hub my_chat_member failed: %s", exc)
'''


def patch_channel_hub_runtime(code: str) -> str:
    """Inject Channel Hub helpers/handlers and expand polling allowed_updates."""
    if "on_channel_hub_post" in code:
        # Refresh injected block when regenerating from template that already has markers
        # (moderator template starts clean; scenario recompiles replace whole main).
        pass
    else:
        needle = "\nasync def main():\n"
        if needle not in code:
            return code
        code = code.replace(needle, "\n" + CHANNEL_HUB_RUNTIME.strip() + "\n\nasync def main():\n", 1)

    old_poll = "await dp.start_polling(bot)"
    new_poll = (
        "await dp.start_polling(\n"
        "        bot,\n"
        "        allowed_updates=[\n"
        '            "message",\n'
        '            "callback_query",\n'
        '            "channel_post",\n'
        '            "edited_channel_post",\n'
        '            "message_reaction_count",\n'
        '            "chat_member",\n'
        '            "my_chat_member",\n'
        "        ],\n"
        "    )"
    )
    main_tail = code.split("async def main():", 1)[-1] if "async def main():" in code else code
    if old_poll in code and "allowed_updates" not in main_tail:
        code = code.replace(old_poll, new_poll, 1)
    elif "allowed_updates=" in main_tail and "message_reaction_count" not in main_tail:
        # Upgrade existing polling config
        import re as _re

        code = _re.sub(
            r"allowed_updates=\[[^\]]*\]",
            (
                "allowed_updates=[\n"
                '            "message",\n'
                '            "callback_query",\n'
                '            "channel_post",\n'
                '            "edited_channel_post",\n'
                '            "message_reaction_count",\n'
                '            "chat_member",\n'
                '            "my_chat_member",\n'
                "        ]"
            ),
            code,
            count=1,
        )
    return code
