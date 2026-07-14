"""Shared bot SQLite schema helpers: bot globals, inventory, namespace utilities."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from backend.core.app_paths import PROJECTS_DIR

FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ISSUED_PREFIX = "_issued_"

BOT_GLOBALS_DDL = """
CREATE TABLE IF NOT EXISTS bot_globals (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at REAL
)
"""

INVENTORY_ITEMS_DDL = """
CREATE TABLE IF NOT EXISTS inventory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'in_stock',
    assigned_to_user TEXT,
    issued_at REAL,
    created_at REAL NOT NULL
)
"""

INVENTORY_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_inventory_product_status
ON inventory_items(product_id, status, id)
"""


def ensure_extended_bot_tables(conn: sqlite3.Connection) -> None:
    conn.execute(BOT_GLOBALS_DDL)
    conn.execute(INVENTORY_ITEMS_DDL)
    conn.execute(INVENTORY_INDEX_DDL)
    from backend.core.custom_tables import ensure_custom_tables_meta

    ensure_custom_tables_meta(conn)


def normalize_user_field_name(field: str) -> str:
    name = (field or "").strip()
    if name.lower().startswith("user."):
        name = name.split(".", 1)[1].strip()
    return name


def normalize_bot_global_key(key: str) -> str:
    name = (key or "").strip()
    if name.lower().startswith("bot."):
        name = name.split(".", 1)[1].strip()
    return name


def parse_placeholder_key(key: str) -> tuple[str, str]:
    """Return (scope, name) where scope is user|bot|issued|legacy."""
    raw = (key or "").strip()
    if not raw:
        return "legacy", ""
    if "." in raw:
        scope, name = raw.split(".", 1)
        scope = scope.strip().lower()
        name = name.strip()
        if scope in ("user", "bot", "issued") and name:
            return scope, name
    return "legacy", raw


def _scenario_field_names(bot_id: int) -> set[str]:
    path = PROJECTS_DIR / f"bot_{bot_id}" / "scenario.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    fields: set[str] = set()
    for block in data.get("blocks") or []:
        typ = block.get("type")
        payload = block.get("data") or {}
        if typ in ("data", "condition") and payload.get("fieldName"):
            name = normalize_user_field_name(str(payload["fieldName"]))
            if name and FIELD_NAME_RE.match(name):
                fields.add(name)
    return fields


def list_bot_global_keys(conn: sqlite3.Connection) -> list[str]:
    if not _table_exists(conn, "bot_globals"):
        return []
    cur = conn.execute("SELECT key FROM bot_globals ORDER BY key")
    return [str(row[0]) for row in cur.fetchall() if row[0]]


def list_placeholder_suggestions(conn: sqlite3.Connection, bot_id: int) -> list[str]:
    suggestions: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        if item and item not in seen:
            seen.add(item)
            suggestions.append(item)

    for key in ("tg_user_id", "tg_user_name", "tg_user_date", "user_id"):
        add(f"user.{key}" if key != "user_id" else "user.tg_user_id")
        add(key)

    for key in ("now_msk", "current_timestamp", "now", "datetime"):
        add(key)

    if _table_exists(conn, "user_data"):
        cur = conn.execute("SELECT DISTINCT field FROM user_data ORDER BY field")
        for row in cur.fetchall():
            field = str(row[0])
            if field.startswith(ISSUED_PREFIX):
                add(f"issued.{field[len(ISSUED_PREFIX):]}")
            elif field not in ("current_menu_id",):
                add(f"user.{field}")
                add(field)

    for field in sorted(_scenario_field_names(bot_id)):
        add(f"user.{field}")
        add(field)

    for key in list_bot_global_keys(conn):
        add(f"bot.{key}")

    from backend.core.custom_tables import list_custom_table_defs

    for logical, meta in list_custom_table_defs(conn).items():
        key_col = meta["key_column"]
        physical = meta["physical_name"]
        if not _table_exists(conn, physical):
            continue
        cur = conn.execute(f"SELECT {key_col} FROM {physical} ORDER BY rowid LIMIT 50")
        for row in cur.fetchall():
            row_key = str(row[0] or "").strip()
            if not row_key:
                continue
            for col in meta["columns"]:
                add(f"bot.{logical}.{row_key}.{col}")

    add("issued.email")
    add("issued.pass")
    add("issued.key")
    add("issued.code")
    return suggestions


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    )
    return cur.fetchone() is not None


def issue_inventory_item(conn: sqlite3.Connection, product_id: str, user_id: int | str) -> dict[str, Any] | None:
    """FIFO issue in a single IMMEDIATE transaction. Returns parsed content dict or None."""
    pid = str(product_id or "").strip()
    if not pid:
        return None
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            """
            SELECT id, content FROM inventory_items
            WHERE product_id = ? AND status = 'in_stock'
            ORDER BY id ASC
            LIMIT 1
            """,
            (pid,),
        ).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            return None
        item_id = int(row[0])
        raw_content = row[1]
        now = time.time()
        updated = conn.execute(
            """
            UPDATE inventory_items
            SET status = 'issued', assigned_to_user = ?, issued_at = ?
            WHERE id = ? AND status = 'in_stock'
            """,
            (str(user_id), now, item_id),
        ).rowcount
        if updated != 1:
            conn.execute("ROLLBACK")
            return None
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK")
        raise

    try:
        content = json.loads(raw_content) if raw_content else {}
    except (TypeError, json.JSONDecodeError):
        content = {"value": raw_content}
    if not isinstance(content, dict):
        content = {"value": content}
    return {"id": item_id, "product_id": pid, "content": content}


def clear_issued_fields(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute(
        "DELETE FROM user_data WHERE user_id = ? AND field LIKE ?",
        (user_id, ISSUED_PREFIX + "%"),
    )


def store_issued_fields(conn: sqlite3.Connection, user_id: int, content: dict[str, Any]) -> None:
    now = time.time()
    clear_issued_fields(conn, user_id)
    for key, val in content.items():
        safe_key = str(key).strip()
        if not safe_key or not FIELD_NAME_RE.match(safe_key):
            continue
        conn.execute(
            """
            INSERT INTO user_data (user_id, field, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, field) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (user_id, ISSUED_PREFIX + safe_key, "" if val is None else str(val), now),
        )
