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

APPOINTMENTS_DDL = """
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    service TEXT,
    scheduled_for TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    comment TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    moderated_by INTEGER,
    moderated_at TEXT
)
"""

APPOINTMENTS_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_appointments_status_time
ON appointments(status, scheduled_for, id)
"""


def ensure_core_bot_tables(conn: sqlite3.Connection) -> None:
    """Always-on tables for FSM / user storage (no channel/admin clutter)."""
    conn.execute(BOT_GLOBALS_DDL)
    from backend.core.custom_tables import ensure_custom_tables_meta

    ensure_custom_tables_meta(conn)


def ensure_inventory_tables(conn: sqlite3.Connection) -> None:
    conn.execute(INVENTORY_ITEMS_DDL)
    conn.execute(INVENTORY_INDEX_DDL)


def ensure_appointment_tables(conn: sqlite3.Connection) -> None:
    conn.execute(APPOINTMENTS_DDL)
    conn.execute(APPOINTMENTS_INDEX_DDL)
    appointment_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(appointments)").fetchall()
    }
    if "moderated_by" not in appointment_columns:
        conn.execute("ALTER TABLE appointments ADD COLUMN moderated_by INTEGER")
    if "moderated_at" not in appointment_columns:
        conn.execute("ALTER TABLE appointments ADD COLUMN moderated_at TEXT")


# Block types / bot kinds that unlock optional SQLite feature tables
_INVENTORY_TYPES = frozenset({"digital_shop", "payment", "inventory", "inventory_items"})
_APPOINTMENT_TYPES = frozenset({"appointment_node", "appointment"})
_CHANNEL_TYPES = frozenset(
    {
        "channel_hub",
        "forward_to_chat",  # may use chats but not full hub schema — keep off by default
    }
)


def detect_bot_db_features(bot_id: int) -> dict[str, bool]:
    """Infer which optional DB feature packs this bot needs from scenario + config."""
    features = {
        "core": True,
        "inventory": False,
        "appointments": False,
        "channel_hub": False,
    }
    bot_dir = PROJECTS_DIR / f"bot_{bot_id}"
    cfg_path = bot_dir / "config.json"
    try:
        if cfg_path.is_file():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            kind = str(cfg.get("kind") or cfg.get("bot_kind") or "").lower()
            if kind in ("moderator", "channel", "channel_hub"):
                features["channel_hub"] = True
    except (OSError, json.JSONDecodeError, TypeError):
        pass

    scenario_path = bot_dir / "scenario.json"
    try:
        if scenario_path.is_file():
            data = json.loads(scenario_path.read_text(encoding="utf-8"))
            for block in data.get("blocks") or []:
                typ = str(block.get("type") or "").strip()
                if typ in _INVENTORY_TYPES:
                    features["inventory"] = True
                if typ in _APPOINTMENT_TYPES:
                    features["appointments"] = True
                # Explicit channel-related plugins only (not forward_to_chat alone)
                if typ.startswith("channel_") or typ in ("moderation", "publisher"):
                    features["channel_hub"] = True
    except (OSError, json.JSONDecodeError, TypeError):
        pass

    return features


def ensure_feature_tables(conn: sqlite3.Connection, features: dict[str, bool] | None = None) -> None:
    """Create optional tables only when the bot's feature set requires them."""
    ensure_core_bot_tables(conn)
    feats = features or {}
    if feats.get("inventory"):
        ensure_inventory_tables(conn)
    if feats.get("appointments"):
        ensure_appointment_tables(conn)
    if feats.get("channel_hub"):
        from backend.core.channel_hub_store import ensure_channel_hub_tables

        ensure_channel_hub_tables(conn)


def ensure_extended_bot_tables(conn: sqlite3.Connection, bot_id: int | None = None) -> None:
    """Backward-compatible entry: core always; optional packs when bot_id features say so.

    Without bot_id, only core tables are ensured (no channel hub auto-create).
    Callers that need channel tables must pass bot_id with channel features or call
    ensure_channel_hub_tables explicitly (Channel Hub routes do).
    """
    features = detect_bot_db_features(bot_id) if bot_id is not None else {"core": True}
    ensure_feature_tables(conn, features)


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
            elif (
                field not in ("current_menu_id",)
                and not field.startswith("_pending_")
                and not field.startswith("_fwd_pending_")
            ):
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
                add(f"table.{logical}.{row_key}.{col}")

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
