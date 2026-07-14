"""Bot user_data.db orchestration: tables, CRUD, import."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import defaultdict
from typing import Any

from backend.core.analytics_import import ImportValidationError, ensure_bot_user_db, merge_into_bot_db
from backend.core.custom_tables import (
    CustomTableError,
    create_custom_table,
    custom_table_meta_for_manager,
    delete_custom_table,
    ensure_custom_tables_meta,
    get_custom_table_def,
    list_custom_table_defs,
)
from backend.core.app_paths import PROJECTS_DIR

TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_ROWS = 10_000

CORE_USER_COLUMNS = ("tg_user_id", "tg_user_name", "tg_user_date")
INTERNAL_USER_FIELDS = frozenset({"current_menu_id"})
TABLE_ORDER = ("users_wide", "bot_globals", "inventory_items", "users", "user_data", "activity_log")

MANAGED_TABLES: dict[str, dict[str, Any]] = {
    "users_wide": {
        "label": "Users (all fields)",
        "primary_key": ["tg_user_id"],
        "editable_columns": ["tg_user_name", "tg_user_date"],
        "use_rowid": False,
        "virtual": True,
    },
    "bot_globals": {
        "label": "Bot globals (bot.*)",
        "primary_key": ["key"],
        "editable_columns": ["value", "updated_at"],
        "use_rowid": False,
    },
    "inventory_items": {
        "label": "Inventory items",
        "primary_key": ["id"],
        "editable_columns": ["product_id", "content", "status", "assigned_to_user", "issued_at", "created_at"],
        "use_rowid": False,
    },
    "users": {
        "label": "Users (core)",
        "primary_key": ["tg_user_id"],
        "editable_columns": ["tg_user_name", "tg_user_date"],
        "use_rowid": False,
    },
    "user_data": {
        "label": "User fields (raw)",
        "primary_key": ["user_id", "field"],
        "editable_columns": ["value", "updated_at"],
        "use_rowid": False,
    },
    "activity_log": {
        "label": "Activity log",
        "primary_key": ["rowid"],
        "editable_columns": ["user_id", "event_time", "event_type", "block_id", "direction"],
        "use_rowid": True,
    },
}


class DatabaseManagerError(ValueError):
    """Invalid table, row, or mutation request."""


def _connect(bot_id: int) -> sqlite3.Connection:
    db_path = ensure_bot_user_db(bot_id)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_custom_tables_meta(conn)
    return conn


def _table_meta(bot_id: int, conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    if table in MANAGED_TABLES:
        return MANAGED_TABLES[table]
    custom = get_custom_table_def(conn, table)
    if not custom:
        raise DatabaseManagerError(f"Table not available: {table!r}")
    columns = ["id", *custom["columns"]]
    return {
        "label": f"Custom: {table}",
        "primary_key": ["id"],
        "editable_columns": list(custom["columns"]),
        "use_rowid": False,
        "virtual": False,
        "custom": True,
        "physical_name": custom["physical_name"],
        "columns": columns,
    }


def _validate_table(table: str, conn: sqlite3.Connection | None = None) -> str:
    name = (table or "").strip()
    if not name or not TABLE_NAME_RE.match(name):
        raise DatabaseManagerError("Invalid table name")
    if name in MANAGED_TABLES:
        return name
    if conn is not None and get_custom_table_def(conn, name):
        return name
    raise DatabaseManagerError(f"Table not available: {table!r}")


def _validate_field_name(field: str) -> str:
    name = (field or "").strip()
    if not name or not TABLE_NAME_RE.match(name):
        raise DatabaseManagerError(f"Invalid field name: {field!r}")
    return name


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    )
    return cur.fetchone() is not None


def _column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [str(row[1]) for row in cur.fetchall()]


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
            name = str(payload["fieldName"]).strip()
            if name and TABLE_NAME_RE.match(name):
                fields.add(name)
    return fields


def _is_internal_field(field: str) -> bool:
    name = (field or "").strip()
    return name in INTERNAL_USER_FIELDS or name.startswith("_issued_")


def _collect_custom_fields(conn: sqlite3.Connection, bot_id: int) -> list[str]:
    db_fields: set[str] = set()
    if _table_exists(conn, "user_data"):
        cur = conn.execute("SELECT DISTINCT field FROM user_data ORDER BY field")
        db_fields = {
            str(row[0])
            for row in cur.fetchall()
            if row[0] and not _is_internal_field(str(row[0]))
        }
    combined = (db_fields | _scenario_field_names(bot_id)) - set(CORE_USER_COLUMNS)
    return sorted(f for f in combined if TABLE_NAME_RE.match(f) and not _is_internal_field(f))


def _scenario_field_types(bot_id: int) -> dict[str, str]:
    path = PROJECTS_DIR / f"bot_{bot_id}" / "scenario.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    types: dict[str, str] = {
        "tg_user_id": "number",
        "tg_user_name": "string",
        "tg_user_date": "string",
    }
    for block in data.get("blocks") or []:
        if block.get("type") != "data":
            continue
        payload = block.get("data") or {}
        name = str(payload.get("fieldName") or "").strip()
        if not name or not TABLE_NAME_RE.match(name):
            continue
        types[name] = "number" if payload.get("fieldType") == "number" else "string"
    return types


def scenario_field_types(bot_id: int) -> dict[str, str]:
    return _scenario_field_types(bot_id)


def scenario_custom_field_names(bot_id: int) -> list[str]:
    """Custom field names from scenario.json plus stored user_data (excludes core user columns)."""
    conn = _connect(bot_id)
    try:
        return _collect_custom_fields(conn, bot_id)
    finally:
        conn.close()


def _distinct_user_ids(conn: sqlite3.Connection) -> list[int]:
    ids: set[int] = set()
    if _table_exists(conn, "users"):
        cur = conn.execute("SELECT tg_user_id FROM users")
        ids.update(int(row[0]) for row in cur.fetchall() if row[0] is not None)
    if _table_exists(conn, "user_data"):
        cur = conn.execute("SELECT DISTINCT user_id FROM user_data")
        ids.update(int(row[0]) for row in cur.fetchall() if row[0] is not None)
    return sorted(ids)


def _load_user_maps(conn: sqlite3.Connection) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, str]]]:
    users: dict[int, dict[str, Any]] = {}
    if _table_exists(conn, "users"):
        for row in conn.execute("SELECT tg_user_id, tg_user_name, tg_user_date FROM users"):
            users[int(row[0])] = {
                "tg_user_id": row[0],
                "tg_user_name": row[1],
                "tg_user_date": row[2],
            }
    data: dict[int, dict[str, str]] = defaultdict(dict)
    if _table_exists(conn, "user_data"):
        for row in conn.execute("SELECT user_id, field, value FROM user_data"):
            data[int(row[0])][str(row[1])] = row[2]
    return users, data


def _users_wide_row(
    user_id: int,
    users: dict[int, dict[str, Any]],
    data: dict[int, dict[str, str]],
    custom_fields: list[str],
) -> dict[str, Any]:
    base = users.get(user_id, {})
    payload = data.get(user_id, {})
    row: dict[str, Any] = {
        "tg_user_id": user_id,
        "tg_user_name": base.get("tg_user_name") or payload.get("tg_user_name") or "",
        "tg_user_date": base.get("tg_user_date") if base.get("tg_user_date") is not None else payload.get("tg_user_date", ""),
    }
    for field in custom_fields:
        row[field] = payload.get(field, "")
    return row


def fetch_users_wide_data(
    bot_id: int,
    conn: sqlite3.Connection,
    *,
    limit: int = MAX_ROWS,
    offset: int = 0,
) -> dict[str, Any]:
    custom_fields = _collect_custom_fields(conn, bot_id)
    columns = list(CORE_USER_COLUMNS) + custom_fields
    editable = ["tg_user_name", "tg_user_date"] + custom_fields

    users, data = _load_user_maps(conn)
    all_ids = _distinct_user_ids(conn)
    total = len(all_ids)
    page_ids = all_ids[offset : offset + limit]
    rows = [_users_wide_row(uid, users, data, custom_fields) for uid in page_ids]

    return {
        "table": "users_wide",
        "label": MANAGED_TABLES["users_wide"]["label"],
        "columns": columns,
        "primary_key": ["tg_user_id"],
        "editable_columns": editable,
        "rows": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def list_tables(bot_id: int) -> dict[str, Any]:
    conn = _connect(bot_id)
    try:
        tables: list[dict[str, Any]] = []
        for name in TABLE_ORDER:
            meta = MANAGED_TABLES[name]
            if meta.get("virtual"):
                if name == "users_wide":
                    count = len(_distinct_user_ids(conn))
                    custom_fields = _collect_custom_fields(conn, bot_id)
                    editable = ["tg_user_name", "tg_user_date"] + custom_fields
                    tables.append(
                        {
                            "name": name,
                            "label": meta["label"],
                            "row_count": count,
                            "primary_key": meta["primary_key"],
                            "editable_columns": editable,
                        }
                    )
                continue
            if not _table_exists(conn, name):
                continue
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            entry = {
                "name": name,
                "label": meta["label"],
                "row_count": int(count),
                "primary_key": meta["primary_key"],
                "editable_columns": meta["editable_columns"],
            }
            if name == "bot_globals":
                entry["allow_insert"] = True
            tables.append(entry)

        for logical, cmeta in list_custom_table_defs(conn).items():
            physical = cmeta["physical_name"]
            count = conn.execute(f"SELECT COUNT(*) FROM {physical}").fetchone()[0]
            tables.append(
                custom_table_meta_for_manager(logical, cmeta, int(count))
                | {"allow_insert": True}
            )

        return {"tables": tables, "database": f"projects/bot_{bot_id}/user_data.db"}
    finally:
        conn.close()


def fetch_table_data(bot_id: int, table: str, *, limit: int = MAX_ROWS, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(int(limit), MAX_ROWS))
    offset = max(0, int(offset))

    conn = _connect(bot_id)
    try:
        table = _validate_table(table, conn)
        meta = _table_meta(bot_id, conn, table)
        if meta.get("virtual"):
            if table == "users_wide":
                return fetch_users_wide_data(bot_id, conn, limit=limit, offset=offset)
            raise DatabaseManagerError(f"Virtual table {table!r} is not supported")

        physical = meta.get("physical_name", table)
        if not _table_exists(conn, physical):
            raise DatabaseManagerError(f"Table {table!r} not found in bot database")

        columns = meta.get("columns") or _column_names(conn, physical)
        if meta.get("use_rowid"):
            select_cols = ["rowid"] + [c for c in columns if c != "rowid"]
        else:
            select_cols = columns

        total = conn.execute(f"SELECT COUNT(*) FROM {physical}").fetchone()[0]
        sql = f"SELECT {', '.join(select_cols)} FROM {physical} ORDER BY rowid LIMIT ? OFFSET ?"
        cur = conn.execute(sql, (limit, offset))
        rows = [dict(row) for row in cur.fetchall()]

        result = {
            "table": table,
            "label": meta["label"],
            "columns": select_cols,
            "primary_key": meta["primary_key"],
            "editable_columns": meta["editable_columns"],
            "rows": rows,
            "total": int(total),
            "limit": limit,
            "offset": offset,
        }
        if meta.get("custom"):
            result["custom"] = True
            result["key_column"] = get_custom_table_def(conn, table)["key_column"]
        if table == "bot_globals":
            result["allow_insert"] = True
            result["insert_columns"] = ["key", "value"]
        elif meta.get("custom"):
            result["allow_insert"] = True
        return result
    finally:
        conn.close()


def _build_where(meta: dict[str, Any], primary_key: dict[str, Any]) -> tuple[str, list[Any]]:
    if not isinstance(primary_key, dict) or not primary_key:
        raise DatabaseManagerError("primary_key is required")

    clauses: list[str] = []
    params: list[Any] = []
    for key in meta["primary_key"]:
        if key not in primary_key:
            raise DatabaseManagerError(f"Missing key {key!r} in primary_key")
        clauses.append(f"{key} = ?")
        params.append(primary_key[key])
    return " AND ".join(clauses), params


def _update_users_wide_row(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    values: dict[str, Any],
    custom_fields: list[str],
) -> None:
    core_updates: dict[str, Any] = {}
    field_updates: dict[str, Any] = {}
    for col, val in values.items():
        if col == "tg_user_id":
            continue
        if col in ("tg_user_name", "tg_user_date"):
            core_updates[col] = val
        elif col in custom_fields:
            field_updates[_validate_field_name(col)] = val

    now = time.time()
    if core_updates:
        existing = conn.execute(
            "SELECT 1 FROM users WHERE tg_user_id = ? LIMIT 1",
            (user_id,),
        ).fetchone()
        if existing:
            assignments = ", ".join(f"{col} = ?" for col in core_updates)
            conn.execute(
                f"UPDATE users SET {assignments} WHERE tg_user_id = ?",
                list(core_updates.values()) + [user_id],
            )
        else:
            conn.execute(
                "INSERT INTO users (tg_user_id, tg_user_name, tg_user_date) VALUES (?, ?, ?)",
                (
                    user_id,
                    core_updates.get("tg_user_name", ""),
                    core_updates.get("tg_user_date", now),
                ),
            )

    for field, val in field_updates.items():
        conn.execute(
            """
            INSERT INTO user_data (user_id, field, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, field) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (user_id, field, val, now),
        )


def update_row(
    bot_id: int,
    *,
    table: str,
    primary_key: dict[str, Any],
    values: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(values, dict) or not values:
        raise DatabaseManagerError("values cannot be empty")

    conn = _connect(bot_id)
    try:
        table = _validate_table(table, conn)
        if table == "users_wide":
            if "tg_user_id" not in primary_key:
                raise DatabaseManagerError("Missing tg_user_id in primary_key")
            user_id = int(primary_key["tg_user_id"])
            custom_fields = _collect_custom_fields(conn, bot_id)
            allowed = {"tg_user_name", "tg_user_date", *custom_fields}
            filtered = {k: v for k, v in values.items() if k in allowed}
            if not filtered:
                raise DatabaseManagerError("No editable fields to update")
            _update_users_wide_row(conn, user_id=user_id, values=filtered, custom_fields=custom_fields)
            conn.commit()
            return {"ok": True, "table": table, "updated": 1}

        meta = _table_meta(bot_id, conn, table)
        allowed = set(meta["editable_columns"])
        pk_cols = set(meta["primary_key"])
        physical = meta.get("physical_name", table)

        assignments: list[str] = []
        params: list[Any] = []
        for col, val in values.items():
            if col in pk_cols:
                continue
            if col not in allowed:
                raise DatabaseManagerError(f"Column {col!r} is not editable")
            assignments.append(f"{col} = ?")
            params.append(val)

        if not assignments:
            raise DatabaseManagerError("No fields to update")

        where_sql, where_params = _build_where(meta, primary_key)
        sql = f"UPDATE {physical} SET {', '.join(assignments)} WHERE {where_sql}"
        cur = conn.execute(sql, params + where_params)
        updated = cur.rowcount
        if updated == 0:
            raise DatabaseManagerError("Row not found")
        conn.commit()
        return {"ok": True, "table": table, "updated": updated}
    finally:
        conn.close()


def insert_row(bot_id: int, *, table: str, values: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(values, dict) or not values:
        raise DatabaseManagerError("values cannot be empty")

    conn = _connect(bot_id)
    try:
        table = _validate_table(table, conn)
        meta = _table_meta(bot_id, conn, table)

        if table == "bot_globals":
            key = _validate_field_name(str(values.get("key", "")))
            val = values.get("value", "")
            now = time.time()
            if "updated_at" in values and values["updated_at"] not in (None, ""):
                now = float(values["updated_at"])
            conn.execute(
                """
                INSERT INTO bot_globals (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, "" if val is None else str(val), now),
            )
            conn.commit()
            return {"ok": True, "table": table, "inserted": 1, "key": key}

        if meta.get("custom"):
            physical = meta["physical_name"]
            allowed = set(meta["editable_columns"])
            cols: list[str] = []
            params: list[Any] = []
            for col, val in values.items():
                if col == "id":
                    continue
                if col not in allowed:
                    raise DatabaseManagerError(f"Column {col!r} is not allowed")
                cols.append(col)
                params.append("" if val is None else str(val))
            if not cols:
                raise DatabaseManagerError("No column values provided")
            sql = f"INSERT INTO {physical} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
            cur = conn.execute(sql, params)
            conn.commit()
            return {"ok": True, "table": table, "inserted": 1, "row_id": cur.lastrowid}

        raise DatabaseManagerError(f"Insert is not supported for table {table!r}")
    finally:
        conn.close()


def create_bot_custom_table(
    bot_id: int,
    *,
    name: str,
    columns: list[str],
    key_column: str,
) -> dict[str, Any]:
    conn = _connect(bot_id)
    try:
        created = create_custom_table(
            conn,
            logical_name=name,
            columns=columns,
            key_column=key_column,
        )
        conn.commit()
        return {"ok": True, **created}
    except CustomTableError as exc:
        raise DatabaseManagerError(str(exc)) from exc
    finally:
        conn.close()


def remove_bot_custom_table(bot_id: int, name: str) -> dict[str, Any]:
    conn = _connect(bot_id)
    try:
        delete_custom_table(conn, name)
        conn.commit()
        return {"ok": True, "table": name}
    except CustomTableError as exc:
        raise DatabaseManagerError(str(exc)) from exc
    finally:
        conn.close()


def delete_row(bot_id: int, *, table: str, primary_key: dict[str, Any]) -> dict[str, Any]:
    conn = _connect(bot_id)
    try:
        table = _validate_table(table, conn)
        if table == "users_wide":
            if "tg_user_id" not in primary_key:
                raise DatabaseManagerError("Missing tg_user_id in primary_key")
            user_id = int(primary_key["tg_user_id"])
            conn.execute("DELETE FROM user_data WHERE user_id = ?", (user_id,))
            cur = conn.execute("DELETE FROM users WHERE tg_user_id = ?", (user_id,))
            deleted = cur.rowcount
            conn.commit()
            return {"ok": True, "table": table, "deleted": deleted or 1}

        meta = _table_meta(bot_id, conn, table)
        physical = meta.get("physical_name", table)
        where_sql, where_params = _build_where(meta, primary_key)
        sql = f"DELETE FROM {physical} WHERE {where_sql}"
        cur = conn.execute(sql, where_params)
        deleted = cur.rowcount
        if deleted == 0:
            raise DatabaseManagerError("Row not found")
        conn.commit()
        return {"ok": True, "table": table, "deleted": deleted}
    finally:
        conn.close()


def delete_user_field_data(bot_id: int, field: str) -> dict[str, Any]:
    """Remove a custom field from user_data for all users."""
    name = _validate_field_name(field)
    if _is_internal_field(name):
        raise DatabaseManagerError(f"Cannot delete internal field: {name}")
    if name in CORE_USER_COLUMNS:
        raise DatabaseManagerError(f"Cannot delete core field: {name}")
    conn = _connect(bot_id)
    try:
        if not _table_exists(conn, "user_data"):
            return {"ok": True, "field": name, "deleted": 0}
        cur = conn.execute("DELETE FROM user_data WHERE field = ?", (name,))
        conn.commit()
        return {"ok": True, "field": name, "deleted": cur.rowcount}
    finally:
        conn.close()


def import_database(bot_id: int, file_path: str) -> dict[str, Any]:
    try:
        return merge_into_bot_db(bot_id, file_path)
    except ImportValidationError as exc:
        raise DatabaseManagerError(str(exc)) from exc
