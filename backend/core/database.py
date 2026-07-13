"""Bot user_data.db orchestration: tables, CRUD, import."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from backend.core.analytics_import import ImportValidationError, ensure_bot_user_db, merge_into_bot_db

TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_ROWS = 10_000

MANAGED_TABLES: dict[str, dict[str, Any]] = {
    "users": {
        "label": "Пользователи",
        "primary_key": ["tg_user_id"],
        "editable_columns": ["tg_user_name", "tg_user_date"],
        "use_rowid": False,
    },
    "user_data": {
        "label": "Данные пользователей",
        "primary_key": ["user_id", "field"],
        "editable_columns": ["value", "updated_at"],
        "use_rowid": False,
    },
    "activity_log": {
        "label": "Журнал активности",
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
    return conn


def _validate_table(table: str) -> str:
    name = (table or "").strip()
    if not name or name not in MANAGED_TABLES:
        raise DatabaseManagerError(f"Таблица недоступна: {table!r}")
    if not TABLE_NAME_RE.match(name):
        raise DatabaseManagerError("Некорректное имя таблицы")
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


def list_tables(bot_id: int) -> dict[str, Any]:
    conn = _connect(bot_id)
    try:
        tables: list[dict[str, Any]] = []
        for name, meta in MANAGED_TABLES.items():
            if not _table_exists(conn, name):
                continue
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            tables.append(
                {
                    "name": name,
                    "label": meta["label"],
                    "row_count": int(count),
                    "primary_key": meta["primary_key"],
                    "editable_columns": meta["editable_columns"],
                }
            )
        return {"tables": tables, "database": f"projects/bot_{bot_id}/user_data.db"}
    finally:
        conn.close()


def fetch_table_data(bot_id: int, table: str, *, limit: int = MAX_ROWS, offset: int = 0) -> dict[str, Any]:
    table = _validate_table(table)
    limit = max(1, min(int(limit), MAX_ROWS))
    offset = max(0, int(offset))

    conn = _connect(bot_id)
    try:
        if not _table_exists(conn, table):
            raise DatabaseManagerError(f"Таблица {table!r} не найдена в базе бота")

        meta = MANAGED_TABLES[table]
        columns = _column_names(conn, table)
        if meta["use_rowid"]:
            select_cols = ["rowid"] + [c for c in columns if c != "rowid"]
        else:
            select_cols = columns

        total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        sql = f"SELECT {', '.join(select_cols)} FROM {table} ORDER BY rowid LIMIT ? OFFSET ?"
        cur = conn.execute(sql, (limit, offset))
        rows = [dict(row) for row in cur.fetchall()]

        return {
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
    finally:
        conn.close()


def _build_where(table: str, primary_key: dict[str, Any]) -> tuple[str, list[Any]]:
    meta = MANAGED_TABLES[table]
    if not isinstance(primary_key, dict) or not primary_key:
        raise DatabaseManagerError("primary_key обязателен")

    clauses: list[str] = []
    params: list[Any] = []
    for key in meta["primary_key"]:
        if key not in primary_key:
            raise DatabaseManagerError(f"В primary_key отсутствует ключ {key!r}")
        clauses.append(f"{key} = ?")
        params.append(primary_key[key])
    return " AND ".join(clauses), params


def update_row(
    bot_id: int,
    *,
    table: str,
    primary_key: dict[str, Any],
    values: dict[str, Any],
) -> dict[str, Any]:
    table = _validate_table(table)
    if not isinstance(values, dict) or not values:
        raise DatabaseManagerError("values не могут быть пустыми")

    meta = MANAGED_TABLES[table]
    allowed = set(meta["editable_columns"])
    pk_cols = set(meta["primary_key"])

    assignments: list[str] = []
    params: list[Any] = []
    for col, val in values.items():
        if col in pk_cols:
            continue
        if col not in allowed:
            raise DatabaseManagerError(f"Колонка {col!r} недоступна для редактирования")
        assignments.append(f"{col} = ?")
        params.append(val)

    if not assignments:
        raise DatabaseManagerError("Нет полей для обновления")

    where_sql, where_params = _build_where(table, primary_key)
    sql = f"UPDATE {table} SET {', '.join(assignments)} WHERE {where_sql}"

    conn = _connect(bot_id)
    try:
        cur = conn.execute(sql, params + where_params)
        updated = cur.rowcount
        if updated == 0:
            raise DatabaseManagerError("Строка не найдена")
        conn.commit()
    finally:
        conn.close()

    return {"ok": True, "table": table, "updated": updated}


def delete_row(bot_id: int, *, table: str, primary_key: dict[str, Any]) -> dict[str, Any]:
    table = _validate_table(table)
    where_sql, where_params = _build_where(table, primary_key)
    sql = f"DELETE FROM {table} WHERE {where_sql}"

    conn = _connect(bot_id)
    try:
        cur = conn.execute(sql, where_params)
        deleted = cur.rowcount
        if deleted == 0:
            raise DatabaseManagerError("Строка не найдена")
        conn.commit()
    finally:
        conn.close()

    return {"ok": True, "table": table, "deleted": deleted}


def import_database(bot_id: int, file_path: str) -> dict[str, Any]:
    try:
        return merge_into_bot_db(bot_id, file_path)
    except ImportValidationError as exc:
        raise DatabaseManagerError(str(exc)) from exc
