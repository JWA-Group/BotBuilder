"""SQLite persistence for BotCopilot chat history (keyed by bot_id)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from backend.core.app_paths import get_data_dir

_lock = threading.Lock()
_DB_NAME = "ai_chat_history.db"
_MAX_MESSAGES = 200


def _db_path() -> Path:
    data = get_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    return data / _DB_NAME


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_chat_bot ON ai_chat_messages(bot_id, id)"
    )
    conn.commit()


def _norm_bot_id(bot_id: str | int | None) -> str | None:
    if bot_id is None:
        return None
    s = str(bot_id).strip()
    return s or None


def list_messages(bot_id: str | int | None, *, limit: int = _MAX_MESSAGES) -> list[dict[str, Any]]:
    key = _norm_bot_id(bot_id)
    if not key:
        return []
    with _lock:
        conn = _connect()
        try:
            _ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT role, content, meta_json, created_at
                FROM ai_chat_messages
                WHERE bot_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (key, max(1, min(int(limit or _MAX_MESSAGES), _MAX_MESSAGES))),
            ).fetchall()
        finally:
            conn.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        meta: dict[str, Any] = {}
        try:
            parsed = json.loads(row["meta_json"] or "{}")
            if isinstance(parsed, dict):
                meta = parsed
        except Exception:
            meta = {}
        item: dict[str, Any] = {
            "role": row["role"],
            "content": row["content"] or "",
            "created_at": row["created_at"],
        }
        if meta:
            item["meta"] = meta
            if meta.get("undoable"):
                item["undoable"] = True
            if meta.get("actions"):
                item["actions"] = meta.get("actions")
        out.append(item)
    return out


def append_message(
    bot_id: str | int | None,
    role: str,
    content: str,
    *,
    meta: dict[str, Any] | None = None,
) -> None:
    key = _norm_bot_id(bot_id)
    if not key:
        return
    role_n = (role or "").strip().lower()
    if role_n not in ("user", "assistant", "system", "tool"):
        return
    body = content if content is not None else ""
    meta_json = json.dumps(meta or {}, ensure_ascii=False)
    with _lock:
        conn = _connect()
        try:
            _ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO ai_chat_messages (bot_id, role, content, meta_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key, role_n, body, meta_json, time.time()),
            )
            # Trim oldest beyond cap
            conn.execute(
                """
                DELETE FROM ai_chat_messages
                WHERE bot_id = ? AND id NOT IN (
                    SELECT id FROM ai_chat_messages
                    WHERE bot_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                """,
                (key, key, _MAX_MESSAGES),
            )
            conn.commit()
        finally:
            conn.close()


def replace_history(
    bot_id: str | int | None,
    messages: list[dict[str, Any]],
) -> None:
    """Replace full history for a bot (used when migrating / syncing)."""
    key = _norm_bot_id(bot_id)
    if not key:
        return
    with _lock:
        conn = _connect()
        try:
            _ensure_schema(conn)
            conn.execute("DELETE FROM ai_chat_messages WHERE bot_id = ?", (key,))
            now = time.time()
            for i, msg in enumerate(messages[-_MAX_MESSAGES:]):
                if not isinstance(msg, dict):
                    continue
                role = str(msg.get("role") or "").strip().lower()
                if role not in ("user", "assistant", "system"):
                    continue
                content = str(msg.get("content") or "")
                meta = msg.get("meta") if isinstance(msg.get("meta"), dict) else {}
                if msg.get("undoable"):
                    meta = dict(meta)
                    meta["undoable"] = True
                conn.execute(
                    """
                    INSERT INTO ai_chat_messages (bot_id, role, content, meta_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        key,
                        role,
                        content,
                        json.dumps(meta, ensure_ascii=False),
                        now + i * 0.001,
                    ),
                )
            conn.commit()
        finally:
            conn.close()


def clear_history(bot_id: str | int | None) -> int:
    key = _norm_bot_id(bot_id)
    if not key:
        return 0
    with _lock:
        conn = _connect()
        try:
            _ensure_schema(conn)
            cur = conn.execute("DELETE FROM ai_chat_messages WHERE bot_id = ?", (key,))
            conn.commit()
            return int(cur.rowcount or 0)
        finally:
            conn.close()
