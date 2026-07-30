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


def _set_custom_table_cell(logical_name, row_key, column, value):
    import json
    import re
    import sqlite3
    logical = str(logical_name or "").strip()
    col = str(column or "").strip()
    key_value = str(row_key or "").strip()
    if not key_value:
        return False
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", logical):
        return False
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", col):
        return False
    try:
        conn = sqlite3.connect(USER_DB_PATH)
        meta = conn.execute(
            "SELECT physical_name, key_column, columns_json FROM _bb_custom_tables WHERE logical_name = ?",
            (logical,),
        ).fetchone()
        if not meta:
            conn.close()
            return False
        physical, key_col, columns_json = meta[0], meta[1], meta[2]
        columns = json.loads(columns_json or "[]")
        if col not in columns:
            conn.close()
            return False
        existing = conn.execute(
            f"SELECT id FROM {physical} WHERE {key_col} = ? LIMIT 1",
            (key_value,),
        ).fetchone()
        if existing:
            conn.execute(
                f"UPDATE {physical} SET {col} = ? WHERE id = ?",
                ("" if value is None else str(value), existing[0]),
            )
        else:
            conn.execute(
                f"INSERT INTO {physical} ({key_col}, {col}) VALUES (?, ?)",
                (key_value, "" if value is None else str(value)),
            )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


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


def create_appointment_request(user_id, service, scheduled_for, comment=""):
    import sqlite3
    from datetime import datetime, timezone
    value = str(scheduled_for or "").strip()
    if not value:
        return None
    _init_user_db()
    conn = sqlite3.connect(USER_DB_PATH)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO appointments
           (user_id, service, scheduled_for, status, comment, created_at, updated_at)
           VALUES (?, ?, ?, 'pending', ?, ?, ?)""",
        (
            int(user_id),
            str(service or "").strip(),
            value,
            str(comment or "").strip(),
            now,
            now,
        ),
    )
    conn.commit()
    appointment_id = cur.lastrowid
    conn.close()
    return appointment_id


def get_appointment(appointment_id):
    import sqlite3
    try:
        conn = sqlite3.connect(USER_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM appointments WHERE id = ?",
            (int(appointment_id),),
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def update_appointment_status(appointment_id, status, moderator_id=None):
    import sqlite3
    from datetime import datetime, timezone
    if status not in ("accepted", "rejected", "cancelled"):
        return None
    conn = sqlite3.connect(USER_DB_PATH)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """UPDATE appointments
           SET status = ?, updated_at = ?, moderated_by = ?, moderated_at = ?
           WHERE id = ? AND status = 'pending'""",
        (status, now, moderator_id, now, int(appointment_id)),
    )
    conn.commit()
    conn.close()
    return cur.rowcount == 1


def parse_telegram_id_list(raw):
    import json
    value = raw
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            value = parsed if isinstance(parsed, list) else text
        except (TypeError, ValueError):
            value = text
    if isinstance(value, str):
        value = value.replace(";", ",").replace("\\n", ",").split(",")
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    result = []
    for item in value:
        try:
            telegram_id = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if telegram_id not in result:
            result.append(telegram_id)
    return result


def get_admin_notification_chat_ids(block_override=""):
    import sqlite3
    result = []
    sources = (
        block_override,
        get_bot_global("admin_chat_id"),
        get_bot_global("admin_chat_ids"),
    )
    for source in sources:
        for telegram_id in parse_telegram_id_list(source):
            if telegram_id not in result:
                result.append(telegram_id)
    try:
        conn = sqlite3.connect(USER_DB_PATH)
        rows = conn.execute(
            """SELECT user_id FROM user_data
               WHERE field = 'role' AND lower(trim(value)) = 'admin'"""
        ).fetchall()
        conn.close()
        for row in rows:
            telegram_id = int(row[0])
            if telegram_id not in result:
                result.append(telegram_id)
    except Exception:
        pass
    return result


def is_appointment_moderator(user_id, chat_id=None):
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    explicit = parse_telegram_id_list(get_bot_global("admin_user_ids"))
    if uid in explicit:
        return True
    role = str(get_user_field(uid, "role") or "").strip().lower()
    if role == "admin":
        return True
    # Legacy compatibility is allowed only for a private admin chat.
    notification_ids = get_admin_notification_chat_ids()
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        cid = None
    return cid == uid and uid in notification_ids


def save_pending_input(user_id, payload):
    import json
    set_user_field(
        user_id,
        "_pending_input",
        json.dumps(payload or {}, ensure_ascii=False),
    )


def load_pending_input(user_id):
    import json
    raw = get_user_field(user_id, "_pending_input")
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (TypeError, ValueError):
        return None


def clear_pending_input(user_id):
    set_user_field(user_id, "_pending_input", "")


def _parse_placeholder_key(key):
    raw = (key or "").strip()
    if not raw:
        return "legacy", ""
    if "." in raw:
        scope, name = raw.split(".", 1)
        scope = scope.strip().lower()
        name = name.strip()
        if scope in ("user", "bot", "issued", "table") and name:
            return scope, name
    return "legacy", raw


def resolve_field_value(user_id, key):
    scope, name = _parse_placeholder_key(key)
    if scope == "bot":
        return get_bot_global(name)
    if scope == "table":
        parts = name.split(".")
        if len(parts) == 3:
            return _lookup_custom_table_cell(parts[0], parts[1], parts[2])
        return None
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
    if scope == "table":
        parts = raw.split(".")
        if len(parts) == 4:
            _set_custom_table_cell(parts[1], parts[2], parts[3], value)
    elif scope == "bot" or raw.lower().startswith("bot."):
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
    """)
    appointment_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(appointments)").fetchall()
    }
    if "moderated_by" not in appointment_columns:
        conn.execute("ALTER TABLE appointments ADD COLUMN moderated_by INTEGER")
    if "moderated_at" not in appointment_columns:
        conn.execute("ALTER TABLE appointments ADD COLUMN moderated_at TEXT")
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_appointments_status_time
        ON appointments(status, scheduled_for, id)
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_registry (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            chat_type TEXT,
            username TEXT,
            linked_chat_id INTEGER,
            members_count INTEGER,
            updated_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            telegram_message_id INTEGER NOT NULL,
            text TEXT,
            views_count INTEGER NOT NULL DEFAULT 0,
            forwards_count INTEGER NOT NULL DEFAULT 0,
            comments_count INTEGER NOT NULL DEFAULT 0,
            reactions_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            UNIQUE(channel_id, telegram_message_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            channel_id INTEGER,
            telegram_message_id INTEGER NOT NULL,
            user_id INTEGER,
            username TEXT,
            text TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            moderated INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            UNIQUE(chat_id, telegram_message_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_member_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER,
            username TEXT,
            event_type TEXT NOT NULL,
            invite_link_used TEXT,
            timestamp REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            warning_count INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            last_warned_at REAL,
            UNIQUE(chat_id, user_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS moderation_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL UNIQUE,
            forbidden_keywords TEXT NOT NULL DEFAULT '[]',
            block_links INTEGER NOT NULL DEFAULT 1,
            block_stickers INTEGER NOT NULL DEFAULT 0,
            block_media INTEGER NOT NULL DEFAULT 0,
            anti_flood INTEGER NOT NULL DEFAULT 0,
            max_warnings INTEGER NOT NULL DEFAULT 3,
            mute_duration_minutes INTEGER NOT NULL DEFAULT 60,
            mute_permanent INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS moderation_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            channel_id INTEGER,
            user_id INTEGER,
            username TEXT,
            action TEXT NOT NULL,
            reason TEXT,
            duration_minutes INTEGER,
            message_id INTEGER,
            source TEXT NOT NULL DEFAULT 'auto',
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
