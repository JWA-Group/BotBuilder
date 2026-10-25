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


class DatabaseManagerError(ValueError):
    """Raised for user-facing database manager validation / CRUD failures."""


CORE_USER_COLUMNS = ("tg_user_id", "tg_user_name", "tg_user_date")
INTERNAL_USER_FIELDS = frozenset({"current_menu_id"})
TABLE_ORDER = (
    "users_wide",
    "bot_globals",
    "appointments",
    "inventory_items",
    "channel_posts",
    "channel_comments",
    "channel_member_events",
    "user_warnings",
    "moderation_rules",
    "moderation_actions",
    "channel_registry",
    "users",
    "user_data",
    "activity_log",
)

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
    "appointments": {
        "label": "Appointments",
        "primary_key": ["id"],
        "editable_columns": [
            "service",
            "scheduled_for",
            "status",
            "comment",
            "updated_at",
            "moderated_by",
            "moderated_at",
        ],
        "use_rowid": False,
    },
    "channel_registry": {
        "label": "Channel registry",
        "primary_key": ["chat_id"],
        "editable_columns": ["title", "chat_type", "username", "linked_chat_id", "members_count", "updated_at"],
        "use_rowid": False,
    },
    "channel_posts": {
        "label": "Channel posts",
        "primary_key": ["id"],
        "editable_columns": [
            "text",
            "views_count",
            "forwards_count",
            "comments_count",
            "reactions_count",
            "created_at",
        ],
        "use_rowid": False,
    },
    "channel_comments": {
        "label": "Channel comments",
        "primary_key": ["id"],
        "editable_columns": ["text", "is_deleted", "moderated", "username"],
        "use_rowid": False,
    },
    "channel_member_events": {
        "label": "Channel member events",
        "primary_key": ["id"],
        "editable_columns": ["event_type", "username", "invite_link_used", "timestamp"],
        "use_rowid": False,
    },
    "user_warnings": {
        "label": "User warnings",
        "primary_key": ["id"],
        "editable_columns": ["warning_count", "reason", "username", "last_warned_at"],
        "use_rowid": False,
    },
    "moderation_rules": {
        "label": "Moderation rules",
        "primary_key": ["id"],
        "editable_columns": [
            "forbidden_keywords",
            "block_links",
            "block_stickers",
            "block_media",
            "anti_flood",
            "max_warnings",
            "mute_duration_minutes",
            "mute_permanent",
            "enabled",
            "updated_at",
        ],
        "use_rowid": False,
    },
    "moderation_actions": {
        "label": "Moderation actions",
        "primary_key": ["id"],
        "editable_columns": ["action", "reason", "duration_minutes", "source"],
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


CHANNEL_HUB_TABLES = frozenset(
    {
        "channel_registry",
        "channel_posts",
        "channel_comments",
        "channel_member_events",
        "user_warnings",
        "moderation_rules",
        "moderation_actions",
    }
)
INVENTORY_TABLES = frozenset({"inventory_items"})
APPOINTMENT_TABLES = frozenset({"appointments"})
CORE_VISIBLE_TABLES = frozenset(
    {"users", "user_data", "users_wide", "bot_globals", "activity_log"}
)


def _table_row_count(conn: sqlite3.Connection, name: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
    except sqlite3.Error:
        return 0


def _is_table_relevant(
    name: str,
    *,
    features: dict[str, bool],
    row_count: int,
    custom: bool = False,
) -> bool:
    """Hide unused optional system tables that have no rows and are not in the bot feature set."""
    if custom or name in CORE_VISIBLE_TABLES or name.startswith("custom_"):
        return True
    if name in CHANNEL_HUB_TABLES:
        return bool(features.get("channel_hub")) or row_count > 0
    if name in INVENTORY_TABLES:
        return bool(features.get("inventory")) or row_count > 0
    if name in APPOINTMENT_TABLES:
        return bool(features.get("appointments")) or row_count > 0
    # Unknown physical tables: show if they have data
    return row_count > 0 or name in MANAGED_TABLES


def _connect(bot_id: int) -> sqlite3.Connection:
    db_path = ensure_bot_user_db(bot_id)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    from backend.core.bot_data_store import ensure_extended_bot_tables

    ensure_extended_bot_tables(conn, bot_id=bot_id)
    return conn


def _normalize_affinity(decl_type: str | None) -> str:
    t = (decl_type or "").strip().upper()
    if not t:
        return "TEXT"
    if "INT" in t:
        return "INTEGER"
    if "CHAR" in t or "CLOB" in t or "TEXT" in t:
        return "TEXT"
    if "BLOB" in t:
        return "BLOB"
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "REAL"
    if "BOOL" in t:
        return "BOOLEAN"
    if "NUM" in t or "DEC" in t:
        return "NUMERIC"
    return t.split("(")[0].strip() or "TEXT"


def _coerce_value_for_affinity(value: Any, affinity: str) -> Any:
    """Validate / coerce a cell value for SQLite column affinity. Raises DatabaseManagerError."""
    if value is None or value == "":
        return None if affinity in {"INTEGER", "REAL", "NUMERIC", "BOOLEAN"} else ""
    aff = (affinity or "TEXT").upper()
    if aff == "INTEGER":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        s = str(value).strip()
        if re.fullmatch(r"-?\d+", s):
            return int(s)
        raise DatabaseManagerError(
            f"TYPE MISMATCH: value {value!r} is not valid for INTEGER column"
        )
    if aff == "REAL" or aff == "NUMERIC":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        s = str(value).strip().replace(",", ".")
        try:
            return float(s)
        except ValueError as exc:
            raise DatabaseManagerError(
                f"TYPE MISMATCH: value {value!r} is not valid for {aff} column"
            ) from exc
    if aff == "BOOLEAN":
        if isinstance(value, bool):
            return 1 if value else 0
        s = str(value).strip().lower()
        if s in {"1", "true", "yes", "y", "on"}:
            return 1
        if s in {"0", "false", "no", "n", "off"}:
            return 0
        if re.fullmatch(r"-?\d+", s):
            return 1 if int(s) != 0 else 0
        raise DatabaseManagerError(
            f"TYPE MISMATCH: value {value!r} is not valid for BOOLEAN column"
        )
    return "" if value is None else str(value)


def _pragma_columns(conn: sqlite3.Connection, physical: str) -> list[dict[str, Any]]:
    cols: list[dict[str, Any]] = []
    for row in conn.execute(f"PRAGMA table_info({physical})").fetchall():
        # cid, name, type, notnull, dflt_value, pk
        decl = str(row[2] or "")
        cols.append(
            {
                "name": str(row[1]),
                "type": _normalize_affinity(decl),
                "decl_type": decl or "TEXT",
                "notnull": bool(row[3]),
                "pk": bool(row[5]),
                "default": row[4],
            }
        )
    return cols


def _pragma_foreign_keys(conn: sqlite3.Connection, physical: str) -> list[dict[str, Any]]:
    fks: list[dict[str, Any]] = []
    for row in conn.execute(f"PRAGMA foreign_key_list({physical})").fetchall():
        # id, seq, table, from, to, on_update, on_delete, match
        fks.append(
            {
                "from_table": physical,
                "from_column": str(row[3]),
                "to_table": str(row[2]),
                "to_column": str(row[4] or "id"),
            }
        )
    return fks


def get_schema_erd(bot_id: int, *, relevant_only: bool = True) -> dict[str, Any]:
    """Schema graph for Database Studio ERD (tables, columns, FKs, row counts).

    When relevant_only=True, hide empty optional Channel Hub / inventory /
    appointment tables that the bot's scenario does not use.
    """
    from backend.core.bot_data_store import detect_bot_db_features

    conn = _connect(bot_id)
    try:
        features = detect_bot_db_features(bot_id)
        tables_out: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []
        seen_physical: set[str] = set()

        physical_names: list[str] = []
        for name in TABLE_ORDER:
            meta = MANAGED_TABLES.get(name) or {}
            if meta.get("virtual"):
                continue
            if _table_exists(conn, name):
                physical_names.append(name)
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ):
            n = str(row[0])
            if n not in physical_names and n != "_bb_custom_tables":
                physical_names.append(n)

        for physical in physical_names:
            if physical in seen_physical:
                continue
            seen_physical.add(physical)
            cols = _pragma_columns(conn, physical)
            count = _table_row_count(conn, physical)
            if relevant_only and not _is_table_relevant(
                physical, features=features, row_count=count
            ):
                continue
            label = (MANAGED_TABLES.get(physical) or {}).get("label") or physical
            tables_out.append(
                {
                    "name": physical,
                    "label": label,
                    "row_count": count,
                    "columns": cols,
                    "primary_key": [c["name"] for c in cols if c["pk"]],
                    "virtual": False,
                }
            )

        visible = {t["name"] for t in tables_out}
        for t in tables_out:
            if t.get("virtual"):
                continue
            for fk in _pragma_foreign_keys(conn, t["name"]):
                if fk["to_table"] in visible:
                    relations.append(fk)

        if _table_exists(conn, "users") or _table_exists(conn, "user_data"):
            custom = _collect_custom_fields(conn, bot_id)
            types_map = _scenario_field_types(bot_id)
            uw_cols = [
                {
                    "name": "tg_user_id",
                    "type": "INTEGER",
                    "decl_type": "INTEGER",
                    "notnull": True,
                    "pk": True,
                    "default": None,
                },
                {
                    "name": "tg_user_name",
                    "type": "TEXT",
                    "decl_type": "TEXT",
                    "notnull": False,
                    "pk": False,
                    "default": None,
                },
                {
                    "name": "tg_user_date",
                    "type": "TEXT",
                    "decl_type": "TEXT",
                    "notnull": False,
                    "pk": False,
                    "default": None,
                },
            ]
            for f in custom:
                ft = types_map.get(f, "string")
                aff = "INTEGER" if ft == "number" else "TEXT"
                uw_cols.append(
                    {
                        "name": f,
                        "type": aff,
                        "decl_type": aff,
                        "notnull": False,
                        "pk": False,
                        "default": None,
                    }
                )
            tables_out.insert(
                0,
                {
                    "name": "users_wide",
                    "label": MANAGED_TABLES["users_wide"]["label"],
                    "row_count": len(_distinct_user_ids(conn)),
                    "columns": uw_cols,
                    "primary_key": ["tg_user_id"],
                    "virtual": True,
                },
            )

        return {
            "database": f"projects/bot_{bot_id}/user_data.db",
            "tables": tables_out,
            "relations": relations,
            "features": features,
        }
    finally:
        conn.close()


def _column_affinity_map(conn: sqlite3.Connection, physical: str) -> dict[str, str]:
    return {c["name"]: c["type"] for c in _pragma_columns(conn, physical)}


def _tx_begin(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")


def _tx_commit(conn: sqlite3.Connection) -> None:
    conn.commit()


def _tx_rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.rollback()
    except sqlite3.Error:
        pass


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
    return (
        name in INTERNAL_USER_FIELDS
        or name.startswith("_issued_")
        or name.startswith("_pending_")
        or name.startswith("_fwd_pending_")
    )


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
        field_type = str(payload.get("fieldType") or "string")
        types[name] = field_type if field_type in {"number", "date", "time", "datetime"} else "string"
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

    types_map = _scenario_field_types(bot_id)
    column_types: dict[str, str] = {
        "tg_user_id": "INTEGER",
        "tg_user_name": "TEXT",
        "tg_user_date": "TEXT",
    }
    for f in custom_fields:
        column_types[f] = "INTEGER" if types_map.get(f) == "number" else "TEXT"

    return {
        "table": "users_wide",
        "label": MANAGED_TABLES["users_wide"]["label"],
        "columns": columns,
        "column_types": column_types,
        "columns_meta": [
            {
                "name": c,
                "type": column_types.get(c, "TEXT"),
                "decl_type": column_types.get(c, "TEXT"),
                "notnull": c == "tg_user_id",
                "pk": c == "tg_user_id",
                "default": None,
            }
            for c in columns
        ],
        "primary_key": ["tg_user_id"],
        "editable_columns": editable,
        "rows": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "success": True,
    }


def list_tables(bot_id: int, *, relevant_only: bool = True) -> dict[str, Any]:
    from backend.core.bot_data_store import detect_bot_db_features

    conn = _connect(bot_id)
    try:
        features = detect_bot_db_features(bot_id)
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
            count = int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
            if relevant_only and not _is_table_relevant(
                name, features=features, row_count=count
            ):
                continue
            entry = {
                "name": name,
                "label": meta["label"],
                "row_count": count,
                "primary_key": meta["primary_key"],
                "editable_columns": meta["editable_columns"],
            }
            if name == "bot_globals":
                entry["allow_insert"] = True
            tables.append(entry)

        for logical, cmeta in list_custom_table_defs(conn).items():
            physical = cmeta["physical_name"]
            count = int(conn.execute(f"SELECT COUNT(*) FROM {physical}").fetchone()[0])
            tables.append(
                custom_table_meta_for_manager(logical, cmeta, count)
                | {"allow_insert": True}
            )

        return {
            "tables": tables,
            "database": f"projects/bot_{bot_id}/user_data.db",
            "features": features,
        }
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

        affinity = _column_affinity_map(conn, physical)
        col_meta = {c["name"]: c for c in _pragma_columns(conn, physical)}

        total = conn.execute(f"SELECT COUNT(*) FROM {physical}").fetchone()[0]
        sql = f"SELECT {', '.join(select_cols)} FROM {physical} ORDER BY rowid LIMIT ? OFFSET ?"
        cur = conn.execute(sql, (limit, offset))
        rows = [dict(row) for row in cur.fetchall()]

        result = {
            "table": table,
            "label": meta["label"],
            "columns": select_cols,
            "column_types": {c: affinity.get(c, "TEXT") for c in select_cols if c != "rowid"},
            "columns_meta": [
                col_meta.get(
                    c,
                    {
                        "name": c,
                        "type": affinity.get(c, "TEXT"),
                        "decl_type": affinity.get(c, "TEXT"),
                        "notnull": False,
                        "pk": c in (meta.get("primary_key") or []),
                        "default": None,
                    },
                )
                for c in select_cols
                if c != "rowid"
            ],
            "primary_key": meta["primary_key"],
            "editable_columns": meta["editable_columns"],
            "rows": rows,
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "success": True,
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
        _tx_begin(conn)
        try:
            if table == "users_wide":
                if "tg_user_id" not in primary_key:
                    raise DatabaseManagerError("Missing tg_user_id in primary_key")
                user_id = int(primary_key["tg_user_id"])
                custom_fields = _collect_custom_fields(conn, bot_id)
                allowed = {"tg_user_name", "tg_user_date", *custom_fields}
                types_map = _scenario_field_types(bot_id)
                filtered: dict[str, Any] = {}
                for k, v in values.items():
                    if k not in allowed:
                        continue
                    aff = "INTEGER" if types_map.get(k) == "number" else "TEXT"
                    if k in ("tg_user_name", "tg_user_date"):
                        aff = "TEXT"
                    filtered[k] = _coerce_value_for_affinity(v, aff)
                if not filtered:
                    raise DatabaseManagerError("No editable fields to update")
                _update_users_wide_row(
                    conn, user_id=user_id, values=filtered, custom_fields=custom_fields
                )
                _tx_commit(conn)
                return {"success": True, "ok": True, "table": table, "updated": 1}

            meta = _table_meta(bot_id, conn, table)
            allowed = set(meta["editable_columns"])
            pk_cols = set(meta["primary_key"])
            physical = meta.get("physical_name", table)
            affinity = _column_affinity_map(conn, physical)

            assignments: list[str] = []
            params: list[Any] = []
            for col, val in values.items():
                if col in pk_cols:
                    continue
                if col not in allowed:
                    raise DatabaseManagerError(f"Column {col!r} is not editable")
                coerced = _coerce_value_for_affinity(val, affinity.get(col, "TEXT"))
                assignments.append(f"{col} = ?")
                params.append(coerced)

            if not assignments:
                raise DatabaseManagerError("No fields to update")

            where_sql, where_params = _build_where(meta, primary_key)
            sql = f"UPDATE {physical} SET {', '.join(assignments)} WHERE {where_sql}"
            cur = conn.execute(sql, params + where_params)
            updated = cur.rowcount
            if updated == 0:
                raise DatabaseManagerError("Row not found")
            _tx_commit(conn)
            return {"success": True, "ok": True, "table": table, "updated": updated}
        except DatabaseManagerError:
            _tx_rollback(conn)
            raise
        except sqlite3.IntegrityError as exc:
            _tx_rollback(conn)
            raise DatabaseManagerError(f"SQLITE_CONSTRAINT: {exc}") from exc
        except sqlite3.Error as exc:
            _tx_rollback(conn)
            raise DatabaseManagerError(f"SQLITE_ERROR: {exc}") from exc
    finally:
        conn.close()


def insert_row(bot_id: int, *, table: str, values: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(values, dict) or not values:
        raise DatabaseManagerError("values cannot be empty")

    conn = _connect(bot_id)
    try:
        table = _validate_table(table, conn)
        meta = _table_meta(bot_id, conn, table)
        _tx_begin(conn)
        try:
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
                _tx_commit(conn)
                return {"success": True, "ok": True, "table": table, "inserted": 1, "key": key}

            if meta.get("custom"):
                physical = meta["physical_name"]
                allowed = set(meta["editable_columns"])
                affinity = _column_affinity_map(conn, physical)
                cols: list[str] = []
                params: list[Any] = []
                for col, val in values.items():
                    if col == "id":
                        continue
                    if col not in allowed:
                        raise DatabaseManagerError(f"Column {col!r} is not allowed")
                    cols.append(col)
                    params.append(_coerce_value_for_affinity(val, affinity.get(col, "TEXT")))
                if not cols:
                    raise DatabaseManagerError("No column values provided")
                sql = (
                    f"INSERT INTO {physical} ({', '.join(cols)}) "
                    f"VALUES ({', '.join('?' for _ in cols)})"
                )
                cur = conn.execute(sql, params)
                _tx_commit(conn)
                return {
                    "success": True,
                    "ok": True,
                    "table": table,
                    "inserted": 1,
                    "row_id": cur.lastrowid,
                }

            raise DatabaseManagerError(f"Insert is not supported for table {table!r}")
        except DatabaseManagerError:
            _tx_rollback(conn)
            raise
        except sqlite3.IntegrityError as exc:
            _tx_rollback(conn)
            raise DatabaseManagerError(f"SQLITE_CONSTRAINT: {exc}") from exc
        except sqlite3.Error as exc:
            _tx_rollback(conn)
            raise DatabaseManagerError(f"SQLITE_ERROR: {exc}") from exc
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


def clear_table_data(bot_id: int, *, table: str) -> dict[str, Any]:
    """Delete all rows from a physical (or virtual users_wide) table."""
    conn = _connect(bot_id)
    try:
        table = _validate_table(table, conn)
        meta = _table_meta(bot_id, conn, table)
        _tx_begin(conn)
        try:
            if table == "users_wide":
                cur1 = conn.execute("DELETE FROM user_data")
                cur2 = conn.execute("DELETE FROM users")
                deleted = int(cur1.rowcount or 0) + int(cur2.rowcount or 0)
            else:
                physical = meta.get("physical_name", table)
                if not _table_exists(conn, physical):
                    raise DatabaseManagerError(f"Table {table!r} not found in bot database")
                cur = conn.execute(f"DELETE FROM {physical}")
                deleted = int(cur.rowcount or 0)
            _tx_commit(conn)
            return {"ok": True, "success": True, "table": table, "deleted": deleted}
        except DatabaseManagerError:
            _tx_rollback(conn)
            raise
        except sqlite3.IntegrityError as exc:
            _tx_rollback(conn)
            raise DatabaseManagerError(f"SQLITE_CONSTRAINT: {exc}") from exc
        except sqlite3.Error as exc:
            _tx_rollback(conn)
            raise DatabaseManagerError(f"SQLITE_ERROR: {exc}") from exc
    finally:
        conn.close()


def delete_row(bot_id: int, *, table: str, primary_key: dict[str, Any]) -> dict[str, Any]:
    conn = _connect(bot_id)
    try:
        table = _validate_table(table, conn)
        _tx_begin(conn)
        try:
            if table == "users_wide":
                if "tg_user_id" not in primary_key:
                    raise DatabaseManagerError("Missing tg_user_id in primary_key")
                user_id = int(primary_key["tg_user_id"])
                conn.execute("DELETE FROM user_data WHERE user_id = ?", (user_id,))
                cur = conn.execute("DELETE FROM users WHERE tg_user_id = ?", (user_id,))
                deleted = cur.rowcount
                _tx_commit(conn)
                return {"success": True, "ok": True, "table": table, "deleted": deleted or 1}

            meta = _table_meta(bot_id, conn, table)
            physical = meta.get("physical_name", table)
            where_sql, where_params = _build_where(meta, primary_key)
            sql = f"DELETE FROM {physical} WHERE {where_sql}"
            cur = conn.execute(sql, where_params)
            deleted = cur.rowcount
            if deleted == 0:
                raise DatabaseManagerError("Row not found")
            _tx_commit(conn)
            return {"success": True, "ok": True, "table": table, "deleted": deleted}
        except DatabaseManagerError:
            _tx_rollback(conn)
            raise
        except sqlite3.IntegrityError as exc:
            _tx_rollback(conn)
            raise DatabaseManagerError(f"SQLITE_CONSTRAINT: {exc}") from exc
        except sqlite3.Error as exc:
            _tx_rollback(conn)
            raise DatabaseManagerError(f"SQLITE_ERROR: {exc}") from exc
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
