"""User-defined SQLite tables for bot-wide data (prices, settings, etc.)."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any

TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PHYSICAL_PREFIX = "ct_"
META_TABLE = "_bb_custom_tables"

RESERVED_LOGICAL_NAMES = frozenset(
    {
        "users",
        "user_data",
        "bot_globals",
        "inventory_items",
        "activity_log",
        "users_wide",
        META_TABLE,
        "sqlite_sequence",
    }
)

CUSTOM_TABLES_META_DDL = f"""
CREATE TABLE IF NOT EXISTS {META_TABLE} (
    logical_name TEXT PRIMARY KEY,
    physical_name TEXT NOT NULL UNIQUE,
    key_column TEXT NOT NULL,
    columns_json TEXT NOT NULL,
    created_at REAL NOT NULL
)
"""


class CustomTableError(ValueError):
    """Invalid custom table definition or operation."""


def ensure_custom_tables_meta(conn: sqlite3.Connection) -> None:
    conn.execute(CUSTOM_TABLES_META_DDL)


def _physical_name(logical: str) -> str:
    return PHYSICAL_PREFIX + logical


def _validate_logical_name(name: str) -> str:
    logical = (name or "").strip()
    if not logical or not TABLE_NAME_RE.match(logical):
        raise CustomTableError(f"Invalid table name: {name!r}")
    if logical.startswith("_") or logical in RESERVED_LOGICAL_NAMES:
        raise CustomTableError(f"Table name {logical!r} is reserved")
    return logical


def _validate_column_name(name: str) -> str:
    col = (name or "").strip()
    if not col or not TABLE_NAME_RE.match(col):
        raise CustomTableError(f"Invalid column name: {name!r}")
    if col == "id":
        raise CustomTableError("Column name 'id' is reserved")
    return col


def list_custom_table_defs(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    ensure_custom_tables_meta(conn)
    defs: dict[str, dict[str, Any]] = {}
    cur = conn.execute(
        f"SELECT logical_name, physical_name, key_column, columns_json, created_at FROM {META_TABLE} ORDER BY logical_name"
    )
    for row in cur.fetchall():
        logical = str(row[0])
        try:
            columns = json.loads(row[3] or "[]")
        except json.JSONDecodeError:
            columns = []
        defs[logical] = {
            "logical_name": logical,
            "physical_name": str(row[1]),
            "key_column": str(row[2]),
            "columns": columns if isinstance(columns, list) else [],
            "created_at": row[4],
        }
    return defs


def get_custom_table_def(conn: sqlite3.Connection, logical_name: str) -> dict[str, Any] | None:
    return list_custom_table_defs(conn).get(logical_name)


def is_custom_table(logical_name: str, defs: dict[str, dict[str, Any]] | None = None) -> bool:
    return logical_name in (defs or {})


def create_custom_table(
    conn: sqlite3.Connection,
    *,
    logical_name: str,
    columns: list[str],
    key_column: str,
) -> dict[str, Any]:
    ensure_custom_tables_meta(conn)
    logical = _validate_logical_name(logical_name)
    if get_custom_table_def(conn, logical):
        raise CustomTableError(f"Table {logical!r} already exists")

    normalized_cols: list[str] = []
    seen: set[str] = set()
    for raw in columns:
        col = _validate_column_name(str(raw))
        if col in seen:
            raise CustomTableError(f"Duplicate column: {col!r}")
        seen.add(col)
        normalized_cols.append(col)
    if not normalized_cols:
        raise CustomTableError("At least one column is required")

    key_col = _validate_column_name(key_column)
    if key_col not in normalized_cols:
        raise CustomTableError(f"Key column {key_col!r} must be listed in columns")

    physical = _physical_name(logical)
    col_defs = ", ".join(f"{col} TEXT" for col in normalized_cols)
    conn.execute(
        f"CREATE TABLE {physical} (id INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs})"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{physical}_{key_col} ON {physical}({key_col})"
    )
    now = time.time()
    conn.execute(
        f"""
        INSERT INTO {META_TABLE} (logical_name, physical_name, key_column, columns_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (logical, physical, key_col, json.dumps(normalized_cols, ensure_ascii=False), now),
    )
    return {
        "logical_name": logical,
        "physical_name": physical,
        "key_column": key_col,
        "columns": normalized_cols,
        "created_at": now,
    }


def delete_custom_table(conn: sqlite3.Connection, logical_name: str) -> None:
    ensure_custom_tables_meta(conn)
    logical = _validate_logical_name(logical_name)
    meta = get_custom_table_def(conn, logical)
    if not meta:
        raise CustomTableError(f"Table {logical!r} not found")
    physical = meta["physical_name"]
    conn.execute(f"DROP TABLE IF EXISTS {physical}")
    conn.execute(f"DELETE FROM {META_TABLE} WHERE logical_name = ?", (logical,))


def lookup_custom_cell(
    conn: sqlite3.Connection,
    logical_name: str,
    row_key: str,
    column: str,
) -> str | None:
    meta = get_custom_table_def(conn, logical_name)
    if not meta:
        return None
    col = _validate_column_name(column)
    if col not in meta["columns"]:
        return None
    physical = meta["physical_name"]
    key_col = meta["key_column"]
    cur = conn.execute(
        f"SELECT {col} FROM {physical} WHERE {key_col} = ? LIMIT 1",
        (str(row_key),),
    )
    row = cur.fetchone()
    return None if row is None else row[0]


def custom_table_meta_for_manager(logical: str, meta: dict[str, Any], row_count: int) -> dict[str, Any]:
    columns = ["id", *meta["columns"]]
    return {
        "name": logical,
        "label": f"Custom: {logical}",
        "row_count": row_count,
        "primary_key": ["id"],
        "editable_columns": list(meta["columns"]),
        "custom": True,
        "key_column": meta["key_column"],
    }
