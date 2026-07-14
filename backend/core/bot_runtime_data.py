"""Runtime data layer stitched into generated bot main.py (globals, inventory, namespaces)."""

from __future__ import annotations

BOT_DATA_RUNTIME_MARKER = "__BOT_DATA_RUNTIME__"

BOT_DATA_RUNTIME = '''
ISSUED_FIELD_PREFIX = "_issued_"


def _normalize_user_field(field):
    name = (field or "").strip()
    if name.lower().startswith("user."):
        name = name.split(".", 1)[1].strip()
    return name


def _normalize_bot_key(key):
    name = (key or "").strip()
    if name.lower().startswith("bot."):
        name = name.split(".", 1)[1].strip()
    return name


def get_bot_global(key):
    import sqlite3
    import time
    safe = _normalize_bot_key(key)
    if not safe:
        return None
    parts = safe.split(".")
    if len(parts) >= 3:
        val = _lookup_custom_table_cell(parts[0], parts[1], parts[2])
        if val is not None:
            return val
    try:
        conn = sqlite3.connect(USER_DB_PATH)
        row = conn.execute(
            "SELECT value FROM bot_globals WHERE key = ?",
            (safe,),
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def _lookup_custom_table_cell(logical_name, row_key, column):
    import sqlite3
    import re
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(logical_name or "")):
        return None
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(column or "")):
        return None
    try:
        conn = sqlite3.connect(USER_DB_PATH)
        meta = conn.execute(
            "SELECT physical_name, key_column, columns_json FROM _bb_custom_tables WHERE logical_name = ?",
            (str(logical_name),),
        ).fetchone()
        if not meta:
            conn.close()
            return None
        physical, key_col, columns_json = meta[0], meta[1], meta[2]
        import json
        columns = json.loads(columns_json or "[]")
        if column not in columns:
            conn.close()
            return None
        row = conn.execute(
            f"SELECT {column} FROM {physical} WHERE {key_col} = ? LIMIT 1",
            (str(row_key),),
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def set_bot_global(key, value):
    import sqlite3
    import time
    safe = _normalize_bot_key(key)
    if not safe:
        return
    _init_user_db()
    conn = sqlite3.connect(USER_DB_PATH)
    conn.execute(
        """INSERT INTO bot_globals (key, value, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (safe, "" if value is None else str(value), time.time()),
    )
    conn.commit()
    conn.close()


def _parse_placeholder_key(key):
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


def resolve_field_value(user_id, key):
    scope, name = _parse_placeholder_key(key)
    if scope == "bot":
        return get_bot_global(name)
    if scope == "issued":
        return get_user_field(user_id, ISSUED_FIELD_PREFIX + name)
    if scope == "user":
        val = get_user_field(user_id, name)
        if val is not None:
            return val
        if name == "tg_user_id":
            return get_user_field(user_id, "tg_user_id") or get_user_field(user_id, "user_id")
        return None
    if key in ("current_timestamp", "now_msk", "now", "datetime"):
        return _msk_now_str()
    if key == "user_id":
        val = get_user_field(user_id, "tg_user_id")
        if val is None:
            val = get_user_field(user_id, "user_id")
        return val
    return get_user_field(user_id, key)


def _clear_issued_fields(user_id):
    import sqlite3
    conn = sqlite3.connect(USER_DB_PATH)
    conn.execute(
        "DELETE FROM user_data WHERE user_id = ? AND field LIKE ?",
        (user_id, ISSUED_FIELD_PREFIX + "%"),
    )
    conn.commit()
    conn.close()


def _store_issued_content(user_id, content):
    import sqlite3
    import time
    if not isinstance(content, dict):
        content = {"value": content}
    _clear_issued_fields(user_id)
    conn = sqlite3.connect(USER_DB_PATH)
    now = time.time()
    for k, v in content.items():
        safe = str(k).strip()
        if not safe:
            continue
        conn.execute(
            """INSERT INTO user_data (user_id, field, value, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, field) DO UPDATE SET
                   value = excluded.value, updated_at = excluded.updated_at""",
            (user_id, ISSUED_FIELD_PREFIX + safe, "" if v is None else str(v), now),
        )
    conn.commit()
    conn.close()


def issue_inventory_item(product_id, user_id):
    """FIFO issue with IMMEDIATE transaction. Returns content dict or None."""
    import sqlite3
    import json
    import time
    pid = str(product_id or "").strip()
    if not pid:
        return None
    conn = sqlite3.connect(USER_DB_PATH)
    try:
        conn.execute("BEGIN IMMEDIATE")
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
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()
    try:
        content = json.loads(raw_content) if raw_content else {}
    except Exception:
        content = {"value": raw_content}
    if not isinstance(content, dict):
        content = {"value": content}
    _store_issued_content(user_id, content)
    return content


def apply_scoped_field_value(user_id, raw_field, value):
    raw = (raw_field or "").strip()
    if not raw:
        return
    scope, _ = _parse_placeholder_key(raw)
    if scope == "bot" or raw.lower().startswith("bot."):
        set_bot_global(_normalize_bot_key(raw), value)
    else:
        set_user_field(user_id, _normalize_user_field(raw), value)
'''


def ensure_bot_data_runtime(code: str) -> str:
    if "def issue_inventory_item" in code:
        return code
    marker = BOT_DATA_RUNTIME_MARKER
    if marker in code:
        return code.replace(marker, BOT_DATA_RUNTIME.strip() + "\n\n", 1)
    anchor = "def set_user_field(user_id: int, field: str, value):\n"
    if anchor not in code or "def log_activity" not in code:
        return code
    insert_at = code.find("\n\n\ndef log_activity(")
    if insert_at < 0:
        return code
    return code[:insert_at] + "\n\n" + BOT_DATA_RUNTIME.strip() + code[insert_at:]


def patch_init_user_db(code: str) -> str:
    if "CREATE TABLE IF NOT EXISTS bot_globals" in code:
        return code
    needle = "    except Exception:\n        pass\n    conn.commit()\n    json_path = os.path.join(BASE_DIR, \"user_data.json\")"
    insert = '''    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_globals (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'in_stock',
            assigned_to_user TEXT,
            issued_at REAL,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_inventory_product_status
        ON inventory_items(product_id, status, id)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _bb_custom_tables (
            logical_name TEXT PRIMARY KEY,
            physical_name TEXT NOT NULL UNIQUE,
            key_column TEXT NOT NULL,
            columns_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.commit()
    json_path = os.path.join(BASE_DIR, "user_data.json")'''
    if needle not in code:
        return code
    return code.replace(needle, insert, 1)


def patch_resolve_text(code: str) -> str:
    if "def resolve_field_value" in code and "resolve_field_value(user_id, key)" in code:
        # Already patched resolve_text body
        if 're.finditer(r"\\\\{\\\\{([a-zA-Z0-9_.]+)\\\\}\\\\}"' in code or 're.finditer(r"\\{\\{([a-zA-Z0-9_.]+)\\}\\}"' in code:
            return code
    old = '''def resolve_text(text: str, user_id: int) -> str:
    """Подстановка {{поле}} из user_data, алиасы и дата/время (для блока «Данные» и текста)."""
    if not text:
        return text
    result = text
    import re
    for m in re.finditer(r"\\{\\{([a-zA-Z0-9_]+)\\}\\}", text):
        key = m.group(1)
        if key in ("current_timestamp", "now_msk", "now", "datetime"):
            val = _msk_now_str()
        elif key == "user_id":
            val = get_user_field(user_id, "tg_user_id")
            if val is None:
                val = get_user_field(user_id, "user_id")
        else:
            val = get_user_field(user_id, key)
        result = result.replace("{{" + key + "}}", _format_value_for_display(val) if val is not None else "")
    return result'''
    new = '''def resolve_text(text: str, user_id: int) -> str:
    """Substitute {{user.field}}, {{bot.key}}, {{issued.key}}, or legacy {{field}}."""
    if not text:
        return text
    import re
    result = text
    for m in re.finditer(r"\\{\\{([a-zA-Z0-9_.]+)\\}\\}", text):
        key = m.group(1)
        val = resolve_field_value(user_id, key)
        result = result.replace("{{" + key + "}}", _format_value_for_display(val) if val is not None else "")
    return result'''
    if old in code:
        return code.replace(old, new, 1)
    return code


def patch_scoped_field_setters(code: str) -> str:
    if "apply_scoped_field_value" not in code:
        return code
    if "apply_scoped_field_value(user_id, field," in code:
        return code
    return code.replace(
        "set_user_field(user_id, field, val)",
        "apply_scoped_field_value(user_id, field, val)",
    ).replace(
        "set_user_field(user_id, field, phone)",
        "apply_scoped_field_value(user_id, field, phone)",
    ).replace(
        "set_user_field(user_id, field, val)",
        "apply_scoped_field_value(user_id, field, val)",
    )
