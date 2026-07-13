"""Secure merge of external SQLite/JSON exports into a bot's user_data.db."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from backend.core.app_paths import PROJECTS_DIR

ALLOWED_SUFFIXES = {".db", ".sqlite", ".json"}


class ImportValidationError(ValueError):
    """Schema or file validation failed before merge."""


def bot_db_path(bot_id: int) -> Path:
    return PROJECTS_DIR / f"bot_{bot_id}" / "user_data.db"


def ensure_bot_user_db(bot_id: int) -> Path:
    bot_dir = PROJECTS_DIR / f"bot_{bot_id}"
    bot_dir.mkdir(parents=True, exist_ok=True)
    db_path = bot_dir / "user_data.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                tg_user_id INTEGER PRIMARY KEY,
                tg_user_name TEXT,
                tg_user_date REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_data (
                user_id INTEGER NOT NULL,
                field TEXT NOT NULL,
                value TEXT,
                updated_at REAL,
                PRIMARY KEY (user_id, field)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_data_user ON user_data(user_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                user_id INTEGER NOT NULL,
                event_time REAL NOT NULL,
                event_type TEXT,
                block_id TEXT,
                direction TEXT DEFAULT 'inbound'
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_activity_user_time ON activity_log(user_id, event_time)"
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
        if "block_id" not in cols:
            conn.execute("ALTER TABLE activity_log ADD COLUMN block_id TEXT")
        if "direction" not in cols:
            conn.execute(
                "ALTER TABLE activity_log ADD COLUMN direction TEXT DEFAULT 'inbound'"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_activity_block ON activity_log(block_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_activity_direction ON activity_log(direction)"
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def validate_import_path(file_path: str) -> Path:
    if not file_path or not str(file_path).strip():
        raise ImportValidationError("Путь к файлу не указан")
    resolved = Path(file_path).expanduser().resolve()
    if not resolved.is_file():
        raise ImportValidationError(f"Файл не найден: {resolved}")
    if resolved.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ImportValidationError("Поддерживаются только файлы .db, .sqlite и .json")
    return resolved


def _normalize_user_id(value: Any) -> int:
    try:
        uid = int(value)
    except (TypeError, ValueError) as exc:
        raise ImportValidationError(f"Некорректный user_id: {value!r}") from exc
    if uid <= 0:
        raise ImportValidationError(f"user_id должен быть положительным: {uid}")
    return uid


def _normalize_event_time(value: Any) -> float:
    if value is None:
        return time.time()
    try:
        ts = float(value)
    except (TypeError, ValueError) as exc:
        raise ImportValidationError(f"Некорректный event_time: {value!r}") from exc
    if ts > 1_000_000_000_000:
        ts = ts / 1000.0
    return ts


def _normalize_user_data_rows(rows: list[dict[str, Any]]) -> list[tuple[int, str, str, float]]:
    out: list[tuple[int, str, str, float]] = []
    now = time.time()
    for row in rows:
        if not isinstance(row, dict):
            continue
        uid = _normalize_user_id(row.get("user_id"))
        field = str(row.get("field") or "").strip()
        if not field:
            raise ImportValidationError("Запись user_data без field")
        value = row.get("value")
        updated_at = row.get("updated_at")
        try:
            updated = float(updated_at) if updated_at is not None else now
        except (TypeError, ValueError):
            updated = now
        out.append((uid, field, "" if value is None else str(value), updated))
    return out


def _normalize_activity_rows(rows: list[dict[str, Any]]) -> list[tuple[int, float, str]]:
    out: list[tuple[int, float, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        uid = _normalize_user_id(row.get("user_id"))
        event_time = _normalize_event_time(row.get("event_time"))
        event_type = str(row.get("event_type") or "action").strip() or "action"
        out.append((uid, event_time, event_type))
    return out


def _sqlite_table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {str(r[1]).lower() for r in cur.fetchall()}


def _read_sqlite_export(source: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        user_cols = _sqlite_table_columns(conn, "user_data")
        activity_cols = _sqlite_table_columns(conn, "activity_log")
        required_user = {"user_id", "field"}
        required_activity = {"user_id", "event_time"}
        if not required_user.issubset(user_cols) and not required_activity.issubset(activity_cols):
            raise ImportValidationError(
                "SQLite-файл не содержит таблиц user_data и activity_log с нужными колонками"
            )

        user_rows: list[dict[str, Any]] = []
        activity_rows: list[dict[str, Any]] = []

        if required_user.issubset(user_cols):
            cur = conn.execute("SELECT user_id, field, value, updated_at FROM user_data")
            user_rows = [dict(r) for r in cur.fetchall()]

        if required_activity.issubset(activity_cols):
            select_cols = ["user_id", "event_time", "event_type"]
            if "event_type" not in activity_cols:
                select_cols = ["user_id", "event_time"]
            cur = conn.execute(f"SELECT {', '.join(select_cols)} FROM activity_log")
            for r in cur.fetchall():
                item = dict(r)
                if "event_type" not in item:
                    item["event_type"] = "action"
                activity_rows.append(item)

        if not user_rows and not activity_rows:
            raise ImportValidationError("В SQLite-файле нет данных для импорта")

        return user_rows, activity_rows
    finally:
        conn.close()


def _read_json_export(source: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImportValidationError(f"Невалидный JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ImportValidationError("JSON должен быть объектом верхнего уровня")

    user_rows: list[dict[str, Any]] = []
    activity_rows: list[dict[str, Any]] = []

    if isinstance(payload.get("user_data"), list):
        user_rows = payload["user_data"]
    elif isinstance(payload.get("users"), dict):
        for uid, fields in payload["users"].items():
            if not isinstance(fields, dict):
                continue
            for field, value in fields.items():
                user_rows.append({"user_id": uid, "field": field, "value": value})

    if isinstance(payload.get("activity_log"), list):
        activity_rows = payload["activity_log"]
    elif isinstance(payload.get("activity"), list):
        activity_rows = payload["activity"]

    if not user_rows and not activity_rows:
        raise ImportValidationError(
            "JSON должен содержать массивы user_data и/или activity_log "
            "(или users / activity в совместимом формате)"
        )

    return user_rows, activity_rows


def load_external_export(source: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    suffix = source.suffix.lower()
    if suffix == ".json":
        return _read_json_export(source)
    return _read_sqlite_export(source)


def merge_into_bot_db(bot_id: int, source_path: str) -> dict[str, Any]:
    source = validate_import_path(source_path)
    target = ensure_bot_user_db(bot_id)

    user_rows_raw, activity_rows_raw = load_external_export(source)
    user_rows = _normalize_user_data_rows(user_rows_raw)
    activity_rows = _normalize_activity_rows(activity_rows_raw)

    conn = sqlite3.connect(target)
    inserted_user = 0
    inserted_activity = 0
    skipped_activity = 0

    try:
        conn.execute("BEGIN IMMEDIATE")
        existing_activity: set[tuple[int, float, str]] = set()
        cur = conn.execute("SELECT user_id, event_time, event_type FROM activity_log")
        for uid, event_time, event_type in cur.fetchall():
            existing_activity.add((int(uid), float(event_time), str(event_type or "action")))

        for uid, field, value, updated_at in user_rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO user_data (user_id, field, value, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (uid, field, value, updated_at),
            )
            inserted_user += 1

            if field == "tg_user_name":
                conn.execute(
                    """
                    INSERT OR IGNORE INTO users (tg_user_id, tg_user_name, tg_user_date)
                    VALUES (?, ?, ?)
                    """,
                    (uid, value, updated_at),
                )

        for uid, event_time, event_type in activity_rows:
            key = (uid, event_time, event_type)
            if key in existing_activity:
                skipped_activity += 1
                continue
            conn.execute(
                "INSERT INTO activity_log (user_id, event_time, event_type) VALUES (?, ?, ?)",
                (uid, event_time, event_type),
            )
            existing_activity.add(key)
            inserted_activity += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "ok": True,
        "bot_id": bot_id,
        "source": str(source),
        "user_data_rows": inserted_user,
        "activity_rows": inserted_activity,
        "activity_skipped_duplicates": skipped_activity,
        "target_db": str(target),
    }
