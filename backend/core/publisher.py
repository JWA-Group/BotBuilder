"""Telegram Post Publisher & Studio — drafts, schedule, send, edit, delete."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

import requests

from backend.core.app_paths import PROJECTS_DIR
from backend.core.broadcast import (
    TELEGRAM_API_BASE,
    TelegramSendError,
    normalize_telegram_html,
    resolve_media_path,
)

log = logging.getLogger("publisher")

PUBLISHER_POSTS_DDL = """
CREATE TABLE IF NOT EXISTS publisher_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL,
    channel_id TEXT NOT NULL,
    channel_title TEXT,
    telegram_message_id INTEGER,
    telegram_message_ids TEXT NOT NULL DEFAULT '[]',
    text_html TEXT NOT NULL DEFAULT '',
    media_files TEXT NOT NULL DEFAULT '[]',
    inline_keyboard TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    scheduled_at REAL,
    error_message TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
"""

PUBLISHER_TAGS_DDL = """
CREATE TABLE IF NOT EXISTS publisher_tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT 'indigo',
    created_at REAL NOT NULL
)
"""

PUBLISHER_PURGED_DDL = """
CREATE TABLE IF NOT EXISTS publisher_purged_keys (
    channel_id TEXT NOT NULL,
    telegram_message_id INTEGER NOT NULL,
    purged_at REAL NOT NULL,
    PRIMARY KEY (channel_id, telegram_message_id)
)
"""

_POST_EXTRA_COLS = (
    ("telegram_message_ids", "TEXT", "'[]'"),
    ("channel_title", "TEXT", "NULL"),
    ("error_message", "TEXT", "NULL"),
    ("updated_at", "REAL", "0"),
    ("bot_id", "INTEGER", "0"),
    ("tags", "TEXT", "'[]'"),
    ("auto_delete_at", "REAL", "NULL"),
    ("deleted_at", "REAL", "NULL"),
    ("deleted_by", "TEXT", "NULL"),
)

TAG_COLORS = (
    "indigo",
    "emerald",
    "amber",
    "rose",
    "sky",
    "purple",
    "teal",
    "orange",
)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


class PublisherError(ValueError):
    """Invalid publisher request."""


def _tg_call(
    token: str,
    method: str,
    *,
    json_payload: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
) -> Any:
    url = TELEGRAM_API_BASE.format(token=token, method=method)
    try:
        resp = requests.post(url, json=json_payload, data=data, files=files, timeout=60)
        payload = resp.json()
    except Exception as exc:
        raise TelegramSendError(f"Telegram request failed: {exc}") from exc
    if not isinstance(payload, dict) or not payload.get("ok"):
        description = str((payload or {}).get("description") or "Unknown error")
        raise TelegramSendError(description)
    return payload.get("result")


def _bot_db(bot_id: int) -> Path:
    return PROJECTS_DIR / f"bot_{bot_id}" / "user_data.db"


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {str(r[1]) for r in conn.execute("PRAGMA table_info(publisher_posts)").fetchall()}
    for name, sql_type, default in _POST_EXTRA_COLS:
        if name not in existing:
            conn.execute(f"ALTER TABLE publisher_posts ADD COLUMN {name} {sql_type} DEFAULT {default}")


def connect_publisher_db(bot_id: int) -> sqlite3.Connection:
    path = _bot_db(bot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(PUBLISHER_POSTS_DDL)
    conn.execute(PUBLISHER_TAGS_DDL)
    conn.execute(PUBLISHER_PURGED_DDL)
    _ensure_columns(conn)
    conn.commit()
    return conn


def _loads(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, (list, dict)):
        return raw
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


def _normalize_tags(tags: list[Any] | None) -> list[dict[str, str]]:
    """App-only metadata. Never included in Telegram send payloads."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in tags or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:48]
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        color = str(item.get("color") or "indigo").strip().lower()
        if color not in TAG_COLORS:
            color = "indigo"
        tid = str(item.get("id") or "").strip() or f"t{len(out)}_{abs(hash(key)) % 10_000_000}"
        out.append({"id": tid, "name": name, "color": color})
        if len(out) >= 20:
            break
    return out


def _tag_usage_count(conn: sqlite3.Connection, name: str) -> int:
    key = name.casefold()
    count = 0
    rows = conn.execute("SELECT tags FROM publisher_posts").fetchall()
    for row in rows:
        for tag in _normalize_tags(_loads(row["tags"] if "tags" in row.keys() else "[]", [])):
            if str(tag.get("name") or "").casefold() == key:
                count += 1
                break
    return count


def upsert_tags(bot_id: int, tags: list[Any] | None) -> list[dict[str, Any]]:
    """Save tags into the bot tag library (catalog)."""
    norm = _normalize_tags(tags)
    if not norm:
        return list_tags(bot_id)
    now = time.time()
    conn = connect_publisher_db(bot_id)
    try:
        for tag in norm:
            existing = conn.execute(
                "SELECT id, name FROM publisher_tags WHERE lower(name) = lower(?) LIMIT 1",
                (tag["name"],),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE publisher_tags SET name = ?, color = ? WHERE id = ?",
                    (tag["name"], tag["color"], existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO publisher_tags (id, name, color, created_at) VALUES (?, ?, ?, ?)",
                    (tag["id"], tag["name"], tag["color"], now),
                )
        conn.commit()
    finally:
        conn.close()
    return list_tags(bot_id)


def list_tags(bot_id: int) -> list[dict[str, Any]]:
    """Return tag library. Seeds missing names from post history once."""
    conn = connect_publisher_db(bot_id)
    try:
        # Seed catalog from posts that already carry tags.
        lib_names = {
            str(r["name"]).casefold()
            for r in conn.execute("SELECT name FROM publisher_tags").fetchall()
        }
        now = time.time()
        for row in conn.execute("SELECT tags FROM publisher_posts").fetchall():
            for tag in _normalize_tags(_loads(row["tags"] if "tags" in row.keys() else "[]", [])):
                key = tag["name"].casefold()
                if key in lib_names:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO publisher_tags (id, name, color, created_at) VALUES (?, ?, ?, ?)",
                    (tag["id"], tag["name"], tag["color"], now),
                )
                lib_names.add(key)
        conn.commit()
        rows = conn.execute(
            "SELECT id, name, color, created_at FROM publisher_tags ORDER BY lower(name) ASC"
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": str(r["id"]),
                    "name": str(r["name"]),
                    "color": str(r["color"] or "indigo"),
                    "created_at": r["created_at"],
                    "usage_count": _tag_usage_count(conn, str(r["name"])),
                }
            )
        return out
    finally:
        conn.close()


def delete_library_tag(bot_id: int, tag_id: str) -> dict[str, Any]:
    """
    Remove a tag from the library catalog.
    Posts that already use the tag keep it in history until purged.
    """
    tid = str(tag_id or "").strip()
    if not tid:
        raise PublisherError("tag_id is required")
    conn = connect_publisher_db(bot_id)
    try:
        row = conn.execute(
            "SELECT id, name, color FROM publisher_tags WHERE id = ? LIMIT 1",
            (tid,),
        ).fetchone()
        if not row:
            # Also allow delete by name
            row = conn.execute(
                "SELECT id, name, color FROM publisher_tags WHERE lower(name) = lower(?) LIMIT 1",
                (tid,),
            ).fetchone()
        if not row:
            raise PublisherError("Tag not found in library")
        usage = _tag_usage_count(conn, str(row["name"]))
        conn.execute("DELETE FROM publisher_tags WHERE id = ?", (row["id"],))
        conn.commit()
        return {
            "ok": True,
            "deleted": True,
            "id": str(row["id"]),
            "name": str(row["name"]),
            "still_in_history": usage > 0,
            "usage_count": usage,
        }
    finally:
        conn.close()


def parse_auto_delete_at(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        return ts if ts > 0 else None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        # ISO-8601 → unix seconds
        from datetime import datetime

        iso = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        return dt.timestamp()
    except ValueError as exc:
        raise PublisherError("Invalid auto_delete_at") from exc


def _row_to_post(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    auto_delete_at = row["auto_delete_at"] if "auto_delete_at" in keys else None
    deleted_at = row["deleted_at"] if "deleted_at" in keys else None
    deleted_by = (row["deleted_by"] if "deleted_by" in keys else None) or ""
    tags_raw = row["tags"] if "tags" in keys else "[]"
    return {
        "id": int(row["id"]),
        "bot_id": int(row["bot_id"] or 0),
        "channel_id": str(row["channel_id"] or ""),
        "channel_title": row["channel_title"] or "",
        "telegram_message_id": row["telegram_message_id"],
        "telegram_message_ids": _loads(row["telegram_message_ids"] if "telegram_message_ids" in keys else "[]", []),
        "text_html": row["text_html"] or "",
        "media_files": _loads(row["media_files"], []),
        "inline_keyboard": _loads(row["inline_keyboard"], []),
        "tags": _normalize_tags(_loads(tags_raw, [])),
        "auto_delete_at": auto_delete_at,
        "deleted_at": deleted_at,
        "deleted_by": deleted_by or None,
        "status": row["status"] or "draft",
        "scheduled_at": row["scheduled_at"],
        "error_message": (row["error_message"] if "error_message" in keys else None) or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"] if "updated_at" in keys else row["created_at"],
    }


def sync_publisher_from_channel_posts(bot_id: int) -> int:
    """
    Disabled permanently.

    Auto-import from channel_posts broke Post Studio delete/purge: removing a row
    from the journal caused it to reappear as a new published post on refresh.
    """
    return 0


def _remember_purged_key(conn: sqlite3.Connection, channel_id: str, telegram_message_id: int | None) -> None:
    if telegram_message_id is None:
        return
    try:
        mid = int(telegram_message_id)
    except (TypeError, ValueError):
        return
    conn.execute(
        """
        INSERT OR REPLACE INTO publisher_purged_keys (channel_id, telegram_message_id, purged_at)
        VALUES (?, ?, ?)
        """,
        (str(channel_id or ""), mid, time.time()),
    )


def _message_ids_from_post(post: dict[str, Any] | None) -> list[int]:
    if not post:
        return []
    ids: list[int] = []
    for raw in post.get("telegram_message_ids") or []:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if post.get("telegram_message_id") is not None:
        try:
            mid = int(post["telegram_message_id"])
            if mid not in ids:
                ids.insert(0, mid)
        except (TypeError, ValueError):
            pass
    return ids


def remove_channel_analytics_posts(
    bot_id: int,
    channel_id: str | int | None,
    message_ids: list[Any] | None,
) -> int:
    """Remove matching rows from channel_posts so Top Posts / analytics stay in sync."""
    try:
        cid = int(channel_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    mids: list[int] = []
    for raw in message_ids or []:
        try:
            mids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not mids:
        return 0

    conn = connect_publisher_db(bot_id)
    try:
        tables = {
            str(r[0])
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "channel_posts" not in tables:
            return 0
        removed = 0
        # channel_id may be stored as TEXT or INTEGER depending on insert path.
        cid_variants = (cid, str(cid), str(channel_id or ""))
        for mid in mids:
            for variant in cid_variants:
                cur = conn.execute(
                    "DELETE FROM channel_posts WHERE channel_id = ? AND telegram_message_id = ?",
                    (variant, mid),
                )
                removed += int(cur.rowcount or 0)
        if removed:
            conn.commit()
        return removed
    finally:
        conn.close()


def sync_channel_posts_with_publisher(bot_id: int) -> int:
    """
    Drop Channel Hub analytics rows for posts removed in Post Studio.

    Also clears tombstones that incorrectly match still-live publisher posts
    (can happen after a bulk journal wipe that seeded every channel_post id).
    """
    conn = connect_publisher_db(bot_id)
    try:
        tables = {
            str(r[0])
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "channel_posts" not in tables:
            return 0
        if "publisher_purged_keys" not in tables:
            conn.execute(PUBLISHER_PURGED_DDL)

        # Live published/scheduled posts must not stay tombstoned.
        conn.execute(
            """
            DELETE FROM publisher_purged_keys
            WHERE EXISTS (
                SELECT 1 FROM publisher_posts pp
                WHERE COALESCE(pp.status, '') != 'deleted'
                  AND CAST(pp.channel_id AS TEXT) = publisher_purged_keys.channel_id
                  AND pp.telegram_message_id = publisher_purged_keys.telegram_message_id
            )
            """
        )

        removed = 0
        cur = conn.execute(
            """
            DELETE FROM channel_posts
            WHERE EXISTS (
                SELECT 1 FROM publisher_purged_keys pk
                WHERE pk.channel_id = CAST(channel_posts.channel_id AS TEXT)
                  AND pk.telegram_message_id = channel_posts.telegram_message_id
            )
            """
        )
        removed += int(cur.rowcount or 0)

        cur = conn.execute(
            """
            DELETE FROM channel_posts
            WHERE EXISTS (
                SELECT 1 FROM publisher_posts pp
                WHERE COALESCE(pp.status, '') = 'deleted'
                  AND CAST(pp.channel_id AS TEXT) = CAST(channel_posts.channel_id AS TEXT)
                  AND pp.telegram_message_id = channel_posts.telegram_message_id
            )
            """
        )
        removed += int(cur.rowcount or 0)
        conn.commit()
        return removed
    finally:
        conn.close()


def list_posts(bot_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
    """Return post history including soft-deleted rows (logs)."""
    # Do not auto-import channel_posts here: purge would be undone on refresh.
    limit = max(1, min(int(limit), 300))
    conn = connect_publisher_db(bot_id)
    try:
        rows = conn.execute(
            """
            SELECT * FROM publisher_posts
            ORDER BY COALESCE(deleted_at, scheduled_at, updated_at, created_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_post(r) for r in rows]
    finally:
        conn.close()


def get_post(bot_id: int, post_id: int) -> dict[str, Any] | None:
    conn = connect_publisher_db(bot_id)
    try:
        row = conn.execute(
            "SELECT * FROM publisher_posts WHERE id = ? LIMIT 1",
            (int(post_id),),
        ).fetchone()
        return _row_to_post(row) if row else None
    finally:
        conn.close()


def _load_bot_token(bot_id: int) -> str:
    cfg = PROJECTS_DIR / f"bot_{bot_id}" / "config.json"
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            token = str((data or {}).get("api_key") or (data or {}).get("token") or "").strip()
            if token:
                return token
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    raise PublisherError("Bot token not found in config.json")


def _media_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "photo"
    if ext in VIDEO_EXT:
        return "video"
    return "document"


def _build_reply_markup(keyboard: list[Any]) -> dict[str, Any] | None:
    rows: list[list[dict[str, str]]] = []
    for row in keyboard or []:
        if not isinstance(row, list):
            continue
        buttons: list[dict[str, str]] = []
        for btn in row:
            if not isinstance(btn, dict):
                continue
            text = str(btn.get("text") or "").strip()
            if not text:
                continue
            btype = str(btn.get("type") or btn.get("btn_type") or "url").strip().lower()
            value = str(btn.get("value") or "").strip()
            if btype in ("url", "url_link", "link") and value:
                buttons.append({"text": text, "url": value})
            elif btype in ("callback", "callback_data", "data") and value:
                buttons.append({"text": text, "callback_data": value[:64]})
        if buttons:
            rows.append(buttons)
    if not rows:
        return None
    return {"inline_keyboard": rows}


def _normalize_media_list(media_files: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in media_files or []:
        if isinstance(item, str):
            out.append({"path": item, "name": Path(item).name})
        elif isinstance(item, dict) and item.get("path"):
            out.append(
                {
                    "path": str(item["path"]),
                    "name": str(item.get("name") or Path(str(item["path"])).name),
                }
            )
    return out[:10]


def publish_to_telegram(
    bot_id: int,
    *,
    channel_id: str | int,
    text_html: str,
    media_files: list[Any] | None = None,
    inline_keyboard: list[Any] | None = None,
) -> dict[str, Any]:
    """Send a post to a Telegram channel. Returns message ids."""
    token = _load_bot_token(bot_id)
    chat_id = int(channel_id)
    html = normalize_telegram_html(text_html or "")
    media = _normalize_media_list(media_files or [])
    markup = _build_reply_markup(inline_keyboard or [])
    message_ids: list[int] = []

    if not media:
        if not html.strip():
            raise PublisherError("Post text is empty")
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": html,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        if markup:
            payload["reply_markup"] = markup
        result = _tg_call(token, "sendMessage", json_payload=payload)
        mid = int(result.get("message_id") or 0)
        if mid:
            message_ids.append(mid)
    elif len(media) == 1:
        path = resolve_media_path(bot_id, media[0]["path"])
        kind = _media_kind(path)
        caption = html[:1024] if html else None
        with path.open("rb") as fh:
            if kind == "photo":
                data = {"chat_id": str(chat_id), "parse_mode": "HTML"}
                if caption:
                    data["caption"] = caption
                files = {"photo": (path.name, fh)}
                if markup:
                    data["reply_markup"] = json.dumps(markup, ensure_ascii=False)
                result = _tg_call(token, "sendPhoto", data=data, files=files)
            elif kind == "video":
                data = {"chat_id": str(chat_id), "parse_mode": "HTML"}
                if caption:
                    data["caption"] = caption
                files = {"video": (path.name, fh)}
                if markup:
                    data["reply_markup"] = json.dumps(markup, ensure_ascii=False)
                result = _tg_call(token, "sendVideo", data=data, files=files)
            else:
                data = {"chat_id": str(chat_id), "parse_mode": "HTML"}
                if caption:
                    data["caption"] = caption
                files = {"document": (path.name, fh)}
                if markup:
                    data["reply_markup"] = json.dumps(markup, ensure_ascii=False)
                result = _tg_call(token, "sendDocument", data=data, files=files)
        mid = int(result.get("message_id") or 0)
        if mid:
            message_ids.append(mid)
    else:
        # Media group (album). Caption on first item; keyboard sent as follow-up.
        media_payload: list[dict[str, Any]] = []
        files: dict[str, Any] = {}
        opened = []
        try:
            for idx, item in enumerate(media):
                path = resolve_media_path(bot_id, item["path"])
                kind = _media_kind(path)
                field = f"file{idx}"
                fh = path.open("rb")
                opened.append(fh)
                files[field] = (path.name, fh)
                entry: dict[str, Any] = {
                    "type": "photo" if kind == "photo" else ("video" if kind == "video" else "document"),
                    "media": f"attach://{field}",
                }
                if idx == 0 and html:
                    entry["caption"] = html[:1024]
                    entry["parse_mode"] = "HTML"
                media_payload.append(entry)
            result = _tg_call(
                token,
                "sendMediaGroup",
                data={
                    "chat_id": str(chat_id),
                    "media": json.dumps(media_payload, ensure_ascii=False),
                },
                files=files,
            )
        finally:
            for fh in opened:
                try:
                    fh.close()
                except Exception:
                    pass
        # sendMediaGroup returns a list
        if isinstance(result, list):
            for msg in result:
                if isinstance(msg, dict) and msg.get("message_id"):
                    message_ids.append(int(msg["message_id"]))
        elif isinstance(result, dict) and result.get("message_id"):
            message_ids.append(int(result["message_id"]))
        if markup:
            follow = _tg_call(
                token,
                "sendMessage",
                json_payload={
                    "chat_id": chat_id,
                    "text": "🔗",
                    "reply_markup": markup,
                },
            )
            mid = int(follow.get("message_id") or 0)
            if mid:
                message_ids.append(mid)

    return {
        "telegram_message_id": message_ids[0] if message_ids else None,
        "telegram_message_ids": message_ids,
    }


def _save_post_row(
    bot_id: int,
    *,
    channel_id: str,
    channel_title: str = "",
    text_html: str = "",
    media_files: list[Any] | None = None,
    inline_keyboard: list[Any] | None = None,
    tags: list[Any] | None = None,
    auto_delete_at: float | None = None,
    status: str = "draft",
    scheduled_at: float | None = None,
    telegram_message_id: int | None = None,
    telegram_message_ids: list[int] | None = None,
    error_message: str = "",
    post_id: int | None = None,
) -> dict[str, Any]:
    now = time.time()
    media = _normalize_media_list(media_files or [])
    keyboard = inline_keyboard or []
    norm_tags = _normalize_tags(tags)
    tags_json = json.dumps(norm_tags, ensure_ascii=False)
    conn = connect_publisher_db(bot_id)
    try:
        if post_id:
            conn.execute(
                """
                UPDATE publisher_posts SET
                    channel_id = ?, channel_title = ?, text_html = ?, media_files = ?,
                    inline_keyboard = ?, tags = ?, auto_delete_at = ?, status = ?, scheduled_at = ?,
                    telegram_message_id = COALESCE(?, telegram_message_id),
                    telegram_message_ids = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    str(channel_id),
                    channel_title or "",
                    text_html or "",
                    json.dumps(media, ensure_ascii=False),
                    json.dumps(keyboard, ensure_ascii=False),
                    tags_json,
                    auto_delete_at,
                    status,
                    scheduled_at,
                    telegram_message_id,
                    json.dumps(telegram_message_ids or [], ensure_ascii=False),
                    error_message or "",
                    now,
                    int(post_id),
                ),
            )
            pid = int(post_id)
        else:
            cur = conn.execute(
                """
                INSERT INTO publisher_posts
                (bot_id, channel_id, channel_title, telegram_message_id, telegram_message_ids,
                 text_html, media_files, inline_keyboard, tags, auto_delete_at,
                 status, scheduled_at, error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(bot_id),
                    str(channel_id),
                    channel_title or "",
                    telegram_message_id,
                    json.dumps(telegram_message_ids or [], ensure_ascii=False),
                    text_html or "",
                    json.dumps(media, ensure_ascii=False),
                    json.dumps(keyboard, ensure_ascii=False),
                    tags_json,
                    auto_delete_at,
                    status,
                    scheduled_at,
                    error_message or "",
                    now,
                    now,
                ),
            )
            pid = int(cur.lastrowid)
        conn.commit()
        row = conn.execute("SELECT * FROM publisher_posts WHERE id = ?", (pid,)).fetchone()
        post = _row_to_post(row)
    finally:
        conn.close()
    return post


def send_now(
    bot_id: int,
    *,
    channel_id: str | int,
    channel_title: str = "",
    text_html: str = "",
    media_files: list[Any] | None = None,
    inline_keyboard: list[Any] | None = None,
    tags: list[Any] | None = None,
    auto_delete_at: float | None = None,
    post_id: int | None = None,
) -> dict[str, Any]:
    # tags / auto_delete_at are app metadata only — never passed to Telegram API.
    try:
        sent = publish_to_telegram(
            bot_id,
            channel_id=channel_id,
            text_html=text_html,
            media_files=media_files,
            inline_keyboard=inline_keyboard,
        )
    except (PublisherError, TelegramSendError) as exc:
        if post_id:
            _save_post_row(
                bot_id,
                channel_id=str(channel_id),
                channel_title=channel_title,
                text_html=text_html,
                media_files=media_files,
                inline_keyboard=inline_keyboard,
                tags=tags,
                auto_delete_at=auto_delete_at,
                status="failed",
                error_message=str(exc),
                post_id=post_id,
            )
        raise PublisherError(str(exc)) from exc

    return _save_post_row(
        bot_id,
        channel_id=str(channel_id),
        channel_title=channel_title,
        text_html=text_html,
        media_files=media_files,
        inline_keyboard=inline_keyboard,
        tags=tags,
        auto_delete_at=auto_delete_at,
        status="published",
        telegram_message_id=sent.get("telegram_message_id"),
        telegram_message_ids=sent.get("telegram_message_ids") or [],
        post_id=post_id,
    )


def schedule_post(
    bot_id: int,
    *,
    channel_id: str | int,
    channel_title: str = "",
    text_html: str = "",
    media_files: list[Any] | None = None,
    inline_keyboard: list[Any] | None = None,
    tags: list[Any] | None = None,
    auto_delete_at: float | None = None,
    scheduled_at: float,
    post_id: int | None = None,
) -> dict[str, Any]:
    if float(scheduled_at) <= time.time() - 5:
        raise PublisherError("scheduled_at must be in the future")
    return _save_post_row(
        bot_id,
        channel_id=str(channel_id),
        channel_title=channel_title,
        text_html=text_html,
        media_files=media_files,
        inline_keyboard=inline_keyboard,
        tags=tags,
        auto_delete_at=auto_delete_at,
        status="scheduled",
        scheduled_at=float(scheduled_at),
        post_id=post_id,
    )


def save_draft(
    bot_id: int,
    *,
    channel_id: str | int,
    channel_title: str = "",
    text_html: str = "",
    media_files: list[Any] | None = None,
    inline_keyboard: list[Any] | None = None,
    tags: list[Any] | None = None,
    auto_delete_at: float | None = None,
    post_id: int | None = None,
) -> dict[str, Any]:
    return _save_post_row(
        bot_id,
        channel_id=str(channel_id),
        channel_title=channel_title,
        text_html=text_html,
        media_files=media_files,
        inline_keyboard=inline_keyboard,
        tags=tags,
        auto_delete_at=auto_delete_at,
        status="draft",
        post_id=post_id,
    )


def edit_post(
    bot_id: int,
    post_id: int,
    *,
    text_html: str | None = None,
    media_files: list[Any] | None = None,
    inline_keyboard: list[Any] | None = None,
    tags: list[Any] | None = None,
    auto_delete_at: Any = ...,
    scheduled_at: float | None = None,
    channel_id: str | None = None,
    channel_title: str | None = None,
    meta_only: bool = False,
) -> dict[str, Any]:
    post = get_post(bot_id, post_id)
    if not post:
        raise PublisherError("Post not found")
    if post["status"] == "deleted":
        raise PublisherError("Deleted posts cannot be edited")

    new_html = text_html if text_html is not None else post["text_html"]
    new_media = media_files if media_files is not None else post["media_files"]
    new_keyboard = inline_keyboard if inline_keyboard is not None else post["inline_keyboard"]
    new_channel = channel_id if channel_id is not None else post["channel_id"]
    new_title = channel_title if channel_title is not None else post["channel_title"]
    new_tags = _normalize_tags(tags if tags is not None else post.get("tags"))
    if auto_delete_at is ...:
        new_auto = post.get("auto_delete_at")
    else:
        new_auto = parse_auto_delete_at(auto_delete_at)

    if meta_only:
        return _save_post_row(
            bot_id,
            channel_id=new_channel,
            channel_title=new_title,
            text_html=post["text_html"],
            media_files=post["media_files"],
            inline_keyboard=post["inline_keyboard"],
            tags=new_tags,
            auto_delete_at=new_auto,
            status=post["status"],
            scheduled_at=post.get("scheduled_at"),
            telegram_message_id=post.get("telegram_message_id"),
            telegram_message_ids=post.get("telegram_message_ids") or [],
            error_message=post.get("error_message") or "",
            post_id=post_id,
        )

    if post["status"] in ("draft", "failed"):
        return _save_post_row(
            bot_id,
            channel_id=new_channel,
            channel_title=new_title,
            text_html=new_html,
            media_files=new_media,
            inline_keyboard=new_keyboard,
            tags=new_tags,
            auto_delete_at=new_auto,
            status="draft",
            post_id=post_id,
        )

    if post["status"] == "scheduled":
        sched = scheduled_at if scheduled_at is not None else post["scheduled_at"]
        return _save_post_row(
            bot_id,
            channel_id=new_channel,
            channel_title=new_title,
            text_html=new_html,
            media_files=new_media,
            inline_keyboard=new_keyboard,
            tags=new_tags,
            auto_delete_at=new_auto,
            status="scheduled",
            scheduled_at=sched,
            post_id=post_id,
        )

    if post["status"] != "published":
        raise PublisherError(f"Cannot edit post with status={post['status']}")

    token = _load_bot_token(bot_id)
    chat_id = int(post["channel_id"])
    mid = post.get("telegram_message_id")
    if not mid:
        raise PublisherError("Published post has no telegram_message_id")

    html = normalize_telegram_html(new_html or "")
    markup = _build_reply_markup(new_keyboard or [])
    has_media = bool(_normalize_media_list(new_media or []))

    try:
        if has_media:
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "message_id": int(mid),
                "caption": html[:1024],
                "parse_mode": "HTML",
            }
            if markup is not None:
                payload["reply_markup"] = markup
            _tg_call(token, "editMessageCaption", json_payload=payload)
        else:
            payload = {
                "chat_id": chat_id,
                "message_id": int(mid),
                "text": html,
                "parse_mode": "HTML",
            }
            if markup is not None:
                payload["reply_markup"] = markup
            _tg_call(token, "editMessageText", json_payload=payload)
        if markup is not None and has_media:
            # Caption edit may ignore markup on some clients — sync explicitly.
            try:
                _tg_call(
                    token,
                    "editMessageReplyMarkup",
                    json_payload={
                        "chat_id": chat_id,
                        "message_id": int(mid),
                        "reply_markup": markup,
                    },
                )
            except TelegramSendError:
                pass
    except TelegramSendError as exc:
        msg = str(exc)
        lower = msg.lower()
        if "message to edit not found" in lower:
            raise PublisherError("Message not found in Telegram (deleted or inaccessible)") from exc
        if "too old" in lower or "can't be edited" in lower:
            raise PublisherError("Telegram no longer allows editing this message (too old)") from exc
        raise PublisherError(msg) from exc

    return _save_post_row(
        bot_id,
        channel_id=new_channel,
        channel_title=new_title,
        text_html=new_html,
        media_files=new_media,
        inline_keyboard=new_keyboard,
        tags=new_tags,
        auto_delete_at=new_auto,
        status="published",
        telegram_message_id=int(mid),
        telegram_message_ids=post.get("telegram_message_ids") or [int(mid)],
        post_id=post_id,
    )


def update_auto_delete(bot_id: int, post_id: int, auto_delete_at: Any) -> dict[str, Any]:
    """Update app-only auto-delete timer without touching Telegram content."""
    return edit_post(bot_id, post_id, auto_delete_at=auto_delete_at, meta_only=True)


def _mark_soft_deleted(
    bot_id: int,
    post_id: int,
    *,
    deleted_by: str = "manual",
    error_message: str = "",
) -> dict[str, Any]:
    now = time.time()
    conn = connect_publisher_db(bot_id)
    try:
        conn.execute(
            """
            UPDATE publisher_posts
            SET status = 'deleted',
                deleted_at = ?,
                deleted_by = ?,
                auto_delete_at = NULL,
                error_message = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (now, deleted_by or "manual", error_message or "", now, int(post_id)),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM publisher_posts WHERE id = ?", (int(post_id),)).fetchone()
        return _row_to_post(row) if row else {"id": post_id, "status": "deleted", "deleted_at": now}
    finally:
        conn.close()


def delete_post(bot_id: int, post_id: int, *, deleted_by: str = "manual") -> dict[str, Any]:
    """Soft-delete: keep history row with status=deleted. Remove from Telegram if published."""
    post = get_post(bot_id, post_id)
    if not post:
        raise PublisherError("Post not found")
    if post["status"] == "deleted":
        return {"ok": True, "deleted": True, "id": post_id, "already": True, "post": post}

    message_ids = _message_ids_from_post(post)

    # Always mark deleted locally first — Telegram/token errors must not block the journal.
    saved = _mark_soft_deleted(
        bot_id,
        post_id,
        deleted_by=deleted_by if deleted_by in ("manual", "auto") else "manual",
        error_message="",
    )

    from_telegram = False
    warnings: list[str] = []
    if post["status"] == "published":
        # Tombstone + drop from Channel Hub Top Posts even if Telegram API fails.
        conn = connect_publisher_db(bot_id)
        try:
            for mid in message_ids:
                _remember_purged_key(conn, str(post.get("channel_id") or ""), mid)
            conn.commit()
        finally:
            conn.close()
        remove_channel_analytics_posts(bot_id, post.get("channel_id"), message_ids)

        try:
            token = _load_bot_token(bot_id)
            chat_id = int(post["channel_id"])
            for mid in message_ids:
                try:
                    _tg_call(
                        token,
                        "deleteMessage",
                        json_payload={"chat_id": chat_id, "message_id": int(mid)},
                    )
                    from_telegram = True
                except TelegramSendError as exc:
                    msg = str(exc)
                    # Already gone in Telegram — treat as successful retract.
                    if "message to delete not found" in msg.lower():
                        from_telegram = True
                    else:
                        warnings.append(msg)
            if warnings and message_ids and len(warnings) == len(message_ids):
                log.warning("Telegram delete failed for all messages bot=%s post=%s", bot_id, post_id)
        except Exception as exc:
            warnings.append(str(exc))
            log.warning("Telegram delete skipped bot=%s post=%s: %s", bot_id, post_id, exc)

        if warnings:
            saved = _mark_soft_deleted(
                bot_id,
                post_id,
                deleted_by=deleted_by if deleted_by in ("manual", "auto") else "manual",
                error_message="; ".join(warnings),
            )

    return {
        "ok": True,
        "deleted": True,
        "id": post_id,
        "from_telegram": from_telegram,
        "warnings": warnings,
        "post": saved,
    }


def purge_post(bot_id: int, post_id: int) -> dict[str, Any]:
    """Permanently remove a post from history logs (deleted or any status)."""
    post = get_post(bot_id, post_id)
    if not post:
        raise PublisherError("Post not found")
    message_ids = _message_ids_from_post(post)
    conn = connect_publisher_db(bot_id)
    try:
        for mid in message_ids:
            _remember_purged_key(conn, str(post.get("channel_id") or ""), mid)
        conn.execute("DELETE FROM publisher_posts WHERE id = ?", (int(post_id),))
        conn.commit()
    finally:
        conn.close()
    remove_channel_analytics_posts(bot_id, post.get("channel_id"), message_ids)
    return {"ok": True, "purged": True, "id": post_id}


def _iter_bot_ids() -> list[int]:
    if not PROJECTS_DIR.is_dir():
        return []
    ids: list[int] = []
    for bot_dir in PROJECTS_DIR.glob("bot_*"):
        if not bot_dir.is_dir():
            continue
        try:
            bot_id = int(bot_dir.name.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        if (bot_dir / "user_data.db").is_file():
            ids.append(bot_id)
    return ids


def process_due_scheduled_posts() -> int:
    """Publish due scheduled posts across all bot projects. Returns count published."""
    published = 0
    now = time.time()
    for bot_id in _iter_bot_ids():
        try:
            conn = connect_publisher_db(bot_id)
            rows = conn.execute(
                """
                SELECT id FROM publisher_posts
                WHERE status = 'scheduled' AND scheduled_at IS NOT NULL AND scheduled_at <= ?
                ORDER BY scheduled_at ASC
                LIMIT 20
                """,
                (now,),
            ).fetchall()
            conn.close()
        except Exception:
            continue
        for row in rows:
            post = get_post(bot_id, int(row["id"]))
            if not post:
                continue
            try:
                send_now(
                    bot_id,
                    channel_id=post["channel_id"],
                    channel_title=post.get("channel_title") or "",
                    text_html=post.get("text_html") or "",
                    media_files=post.get("media_files") or [],
                    inline_keyboard=post.get("inline_keyboard") or [],
                    tags=post.get("tags") or [],
                    auto_delete_at=post.get("auto_delete_at"),
                    post_id=post["id"],
                )
                published += 1
            except Exception as exc:
                log.warning("Scheduled publish failed bot=%s post=%s: %s", bot_id, post["id"], exc)
                try:
                    _save_post_row(
                        bot_id,
                        channel_id=post["channel_id"],
                        channel_title=post.get("channel_title") or "",
                        text_html=post.get("text_html") or "",
                        media_files=post.get("media_files") or [],
                        inline_keyboard=post.get("inline_keyboard") or [],
                        tags=post.get("tags") or [],
                        auto_delete_at=post.get("auto_delete_at"),
                        status="failed",
                        scheduled_at=post.get("scheduled_at"),
                        error_message=str(exc),
                        post_id=post["id"],
                    )
                except Exception:
                    pass
    return published


def process_due_auto_deletes() -> int:
    """Delete published Telegram posts whose auto_delete_at has passed."""
    deleted = 0
    now = time.time()
    for bot_id in _iter_bot_ids():
        try:
            conn = connect_publisher_db(bot_id)
            rows = conn.execute(
                """
                SELECT id FROM publisher_posts
                WHERE status = 'published'
                  AND auto_delete_at IS NOT NULL
                  AND auto_delete_at <= ?
                ORDER BY auto_delete_at ASC
                LIMIT 20
                """,
                (now,),
            ).fetchall()
            conn.close()
        except Exception:
            continue
        for row in rows:
            try:
                delete_post(bot_id, int(row["id"]), deleted_by="auto")
                deleted += 1
            except Exception as exc:
                log.warning("Auto-delete failed bot=%s post=%s: %s", bot_id, row["id"], exc)
    return deleted


_scheduler_task: asyncio.Task | None = None


async def publisher_scheduler_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(process_due_scheduled_posts)
        except Exception as exc:
            log.warning("Publisher scheduler tick failed: %s", exc)
        try:
            await asyncio.to_thread(process_due_auto_deletes)
        except Exception as exc:
            log.warning("Publisher auto-delete tick failed: %s", exc)
        try:
            from backend.core.broadcast_studio import (
                process_due_broadcast_auto_deletes,
                process_due_scheduled_broadcasts,
            )

            await asyncio.to_thread(process_due_scheduled_broadcasts)
            await asyncio.to_thread(process_due_broadcast_auto_deletes)
        except Exception as exc:
            log.warning("Broadcast scheduler tick failed: %s", exc)
        await asyncio.sleep(30)


def start_publisher_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        return
    _scheduler_task = asyncio.create_task(publisher_scheduler_loop())


async def stop_publisher_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
    _scheduler_task = None
