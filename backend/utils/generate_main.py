import json
import logging
import os

from jinja2 import Template, TemplateSyntaxError

from backend.core.app_paths import PROJECTS_DIR as BASE_DIR

_compile_log = logging.getLogger("botbuilder.compile")


def get_bot_platform(bot_id: int) -> str:
    """Платформа бота: только telegram."""
    return "telegram"


def get_bot_kind(bot_id: int) -> str:
    """Bot kind: scenario (default) or moderator (Channel Hub only)."""
    path = os.path.join(BASE_DIR, f"bot_{bot_id}", "config.json")
    if not os.path.isfile(path):
        return "scenario"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        kind = str((data or {}).get("kind") or "scenario").strip().lower()
        return "moderator" if kind == "moderator" else "scenario"
    except (OSError, json.JSONDecodeError, TypeError):
        return "scenario"


MODERATOR_MAIN_TEMPLATE = '''# -*- coding: utf-8 -*-
"""Dedicated Channel Hub moderation bot (no scenario editor)."""
import asyncio
import json
import logging
import os
import socket
import sys
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import ClientSession, TCPConnector

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.environ.get("BOT_DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
USER_DB_PATH = os.path.join(DATA_DIR, "user_data.db")

_log_handlers = []
if os.environ.get("BOTBUILDER_DOCKER", "").strip().lower() in ("1", "true", "yes"):
    _log_handlers.append(logging.StreamHandler(sys.stdout))
_log_path = os.path.join(DATA_DIR, "bot.log")
try:
    _log_handlers.append(logging.FileHandler(_log_path, encoding="utf-8"))
except OSError:
    pass
if not _log_handlers:
    _log_handlers.append(logging.NullHandler())
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=_log_handlers,
    force=True,
)
log = logging.getLogger("bot")

with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
    config = json.load(f)
TOKEN = config.get("api_key") or config.get("token") or ""


class ProxyAwareSession(AiohttpSession):
    async def create_session(self) -> ClientSession:
        if self._should_reset_connector:
            await self.close()
        if self._session is None or self._session.closed:
            self._session = ClientSession(
                connector=TCPConnector(family=socket.AF_INET, limit=100),
                trust_env=True,
            )
            self._should_reset_connector = False
        return self._session


bot = Bot(
    token=TOKEN,
    session=ProxyAwareSession(),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


def _init_user_db():
    import sqlite3
    conn = sqlite3.connect(USER_DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            tg_user_id INTEGER PRIMARY KEY,
            tg_user_name TEXT,
            tg_user_date TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_data (
            user_id INTEGER NOT NULL,
            field TEXT NOT NULL,
            value TEXT,
            updated_at REAL,
            PRIMARY KEY (user_id, field)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS activity_log (
            user_id INTEGER,
            event_time REAL,
            event_type TEXT,
            block_id TEXT,
            direction TEXT
        )"""
    )
    conn.commit()
    conn.close()


_init_user_db()


@dp.message(F.chat.type == "private", F.text)
async def on_private_help(message: types.Message):
    await message.answer(
        "Это бот модерации Менеджера каналов.\\n"
        "Добавьте меня админом в канал и связанную группу обсуждений."
    )


async def main():
    log.info("Connecting to Telegram API...")
    try:
        me = await asyncio.wait_for(bot.get_me(), timeout=45.0)
    except asyncio.TimeoutError:
        log.error("Таймаут подключения к Telegram API (45с).")
        raise SystemExit(1)
    log.info("Start polling as @%s (id=%s) [moderator]", me.username, me.id)
    try:
        await dp.start_polling(bot)
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as exc:
        log.exception("Bot stopped: %s", exc)
        raise
'''


def generate_moderator_main(bot_id: int) -> bool:
    """Generate Channel-Hub-only main.py (no scenario FSM)."""
    from backend.core.channel_hub_runtime import patch_channel_hub_runtime

    bot_path = os.path.join(BASE_DIR, f"bot_{bot_id}")
    os.makedirs(bot_path, exist_ok=True)
    code = patch_channel_hub_runtime(MODERATOR_MAIN_TEMPLATE)
    main_path = os.path.join(bot_path, "main.py")
    with open(main_path, "w", encoding="utf-8") as f:
        f.write(code)
    return True


# --- Шаблон main.py по сценарию (редактор блоков + связи) ---
SCENARIO_MAIN_TEMPLATE = '''# -*- coding: utf-8 -*-
"""Бот, управляемый сценарием (scenario.json). Поддержка команд, данных, условий, медиа."""
import asyncio
import json
import logging
import os
import socket
import sys
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import FSInputFile
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import ClientSession, TCPConnector

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.environ.get("BOT_DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)

_log_handlers = []
if os.environ.get("BOTBUILDER_DOCKER", "").strip().lower() in ("1", "true", "yes"):
    _log_handlers.append(logging.StreamHandler(sys.stdout))
_log_path = os.path.join(DATA_DIR, "bot.log")
if os.path.isdir(_log_path):
    import shutil
    shutil.rmtree(_log_path, ignore_errors=True)
try:
    _log_handlers.append(logging.FileHandler(_log_path, encoding="utf-8"))
except OSError:
    pass
if not _log_handlers:
    _log_handlers.append(logging.NullHandler())
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=_log_handlers,
    force=True,
)
log = logging.getLogger("bot")

with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
    config = json.load(f)
TOKEN = config.get("api_key") or config.get("token") or ""
try:
    BOT_ID = int(config.get("bot_id") or config.get("id") or 0)
except (TypeError, ValueError):
    BOT_ID = 0
if not BOT_ID:
    try:
        BOT_ID = int(os.path.basename(BASE_DIR).replace("bot_", "") or "0")
    except (TypeError, ValueError):
        BOT_ID = 0
# Optional sidecar URL for live telemetry (falls back to bot.log marker only).
API_SIDECAR = (
    os.environ.get("BOTBUILDER_API_URL")
    or config.get("api_url")
    or "http://127.0.0.1:8000"
).rstrip("/")


def _redact_runtime_value(val, depth=0):
    if depth > 3:
        return "[truncated]"
    if isinstance(val, dict):
        out = {}
        for k, v in list(val.items())[:30]:
            ks = str(k).lower()
            if any(s in ks for s in ("token", "password", "secret", "api_key", "authorization")):
                out[str(k)] = "[REDACTED]"
            else:
                out[str(k)] = _redact_runtime_value(v, depth + 1)
        return out
    if isinstance(val, list):
        return [_redact_runtime_value(x, depth + 1) for x in val[:20]]
    if isinstance(val, str):
        s = val
        if len(s) > 400:
            s = s[:399] + "…"
        return s
    if isinstance(val, (int, float, bool)) or val is None:
        return val
    return str(val)[:200]


def _report_node_runtime_error(user_id, block_id, typ, data, ctx, exc):
    """Zero-cost on happy path: only called from except around node dispatch."""
    import traceback
    import urllib.request

    payload = {
        "bot_id": BOT_ID,
        "user_id": user_id,
        "failing_node_id": str(block_id or ""),
        "node_type": str(typ or ""),
        "exception_type": type(exc).__name__,
        "stack_trace": traceback.format_exc(),
        "message": str(exc)[:500],
        "local_variables_snapshot": {
            "data": _redact_runtime_value(data if isinstance(data, dict) else {}),
            "ctx": _redact_runtime_value(
                {
                    k: (ctx or {}).get(k)
                    for k in (
                        "trigger_text",
                        "accept_input",
                        "force_await_input",
                        "last_chat_id",
                    )
                    if isinstance(ctx, dict)
                }
            ),
        },
    }
    try:
        log.error("BB_RUNTIME_ERROR:%s", json.dumps(payload, ensure_ascii=False))
    except Exception:
        log.exception("node runtime error (unserializable payload)")
    # Best-effort push to IDE sidecar (non-blocking short timeout).
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            API_SIDECAR + "/api/ai/runtime-errors",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=0.4)
    except Exception:
        pass


class ProxyAwareSession(AiohttpSession):
    """aiohttp + trust_env: использует системный прокси Windows (VPN/Clash)."""

    async def create_session(self) -> ClientSession:
        if self._should_reset_connector:
            await self.close()
        if self._session is None or self._session.closed:
            self._session = ClientSession(
                connector=TCPConnector(family=socket.AF_INET, limit=100),
                trust_env=True,
            )
            self._should_reset_connector = False
        return self._session


bot = Bot(
    token=TOKEN,
    session=ProxyAwareSession(),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# --- Inbound / outbound dedupe (prevent double menu dispatch & duplicate bubbles) ---
_OUTBOUND_DEDUP = {}  # (chat_id, text) -> monotonic ts
_INBOUND_DEDUP = {}  # user_id -> (message_id, text, ts)
_DEDUP_WINDOW_SEC = 1.0


def _claim_outbound_text(chat_id, text) -> bool:
    """Return False if the same text was already sent to chat_id within 1s."""
    import time

    body = (text if text is not None else "")
    if isinstance(body, str):
        body = body.strip()
    else:
        body = str(body).strip()
    if not body:
        return True
    key = (int(chat_id or 0), body)
    now = time.monotonic()
    prev = _OUTBOUND_DEDUP.get(key)
    if prev is not None and (now - prev) < _DEDUP_WINDOW_SEC:
        log.info("Suppress duplicate outbound chat=%s within 1s", chat_id)
        return False
    _OUTBOUND_DEDUP[key] = now
    if len(_OUTBOUND_DEDUP) > 400:
        cutoff = now - 5.0
        stale = [k for k, v in _OUTBOUND_DEDUP.items() if v < cutoff]
        for k in stale:
            _OUTBOUND_DEDUP.pop(k, None)
    return True


def _claim_inbound_event(user_id, message_id, text) -> bool:
    """
    Single-dispatch debounce: the same Telegram message (or same button text
    within a short race window) is processed only once across menu/text handlers.
    """
    import time

    now = time.monotonic()
    uid = int(user_id or 0)
    mid = int(message_id or 0)
    txt = (text or "").strip()[:200]
    prev = _INBOUND_DEDUP.get(uid)
    if prev:
        p_mid, p_txt, p_ts = prev
        if mid and p_mid == mid and (now - p_ts) < _DEDUP_WINDOW_SEC:
            log.info("Suppress duplicate inbound user=%s message_id=%s", uid, mid)
            return False
        if txt and p_txt == txt and (now - p_ts) < 0.4:
            log.info("Suppress duplicate inbound race user=%s text=%r", uid, txt[:40])
            return False
    _INBOUND_DEDUP[uid] = (mid, txt, now)
    if len(_INBOUND_DEDUP) > 400:
        cutoff = now - 5.0
        stale = [k for k, v in _INBOUND_DEDUP.items() if v[2] < cutoff]
        for k in stale:
            _INBOUND_DEDUP.pop(k, None)
    return True


_raw_bot_send_message = bot.send_message


async def _bot_send_message_deduped(chat_id, text=None, *args, **kwargs):
    body = text if text is not None else kwargs.get("text")
    if body is not None and not _claim_outbound_text(chat_id, body):
        return None
    if text is not None:
        return await _raw_bot_send_message(chat_id, text, *args, **kwargs)
    return await _raw_bot_send_message(chat_id, *args, **kwargs)


bot.send_message = _bot_send_message_deduped


class ScenarioState(StatesGroup):
    in_menu = State()
    awaiting_data_input = State()


def load_scenario():
    path = os.path.join(BASE_DIR, "scenario.json")
    if not os.path.exists(path):
        return {"blocks": [], "connections": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


SCENARIO = load_scenario()
BLOCKS_BY_ID = {b["id"]: b for b in SCENARIO.get("blocks", [])}
CONNECTIONS = SCENARIO.get("connections", [])
NEXT_MAP = {}
for c in CONNECTIONS:
    out = c.get("outputIndex", 0)
    if isinstance(out, str):
        out = out.strip()
        if not out.isdigit():
            # Named ports are not drawn on the canvas; never route them silently to port 0.
            logging.getLogger("bot.scenario").error(
                "BB_SCENARIO_ERROR invalid outputIndex %r on %s -> %s, edge ignored",
                out, c.get("from"), c.get("to"),
            )
            continue
        out = int(out)
    key = (c.get("from"), out)
    if key in NEXT_MAP and NEXT_MAP[key] != c.get("to"):
        logging.getLogger("bot.scenario").warning(
            "BB_SCENARIO_WARNING %s port %s has several targets, using %s (dropped %s)",
            key[0], out, c.get("to"), NEXT_MAP[key],
        )
    NEXT_MAP[key] = c.get("to")


def normalize_button_row_breaks(breaks, count):
    if not count:
        return []
    raw = breaks if isinstance(breaks, list) else [0]
    out = []
    for x in raw:
        try:
            ix = int(x)
        except (TypeError, ValueError):
            continue
        if 0 <= ix < count:
            out.append(ix)
    out.sort()
    if not out or out[0] != 0:
        out.insert(0, 0)
    deduped = []
    for x in out:
        if not deduped or deduped[-1] != x:
            deduped.append(x)
    return deduped


def build_button_rows_from_breaks(items, breaks):
    """Split a flat button list into rows using row-break start indices."""
    if not items:
        return []
    n = len(items)
    b = normalize_button_row_breaks(breaks, n)
    rows = []
    for i, start in enumerate(b):
        end = b[i + 1] if i + 1 < len(b) else n
        if end > start:
            rows.append(items[start:end])
    if not rows:
        rows.append(list(items))
    return rows


# БД уникальна для каждого бота; в Docker — volume ./data → /app/data
USER_DB_PATH = os.path.join(DATA_DIR, "user_data.db")


def _init_user_db():
    import sqlite3
    conn = sqlite3.connect(USER_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            tg_user_id INTEGER PRIMARY KEY,
            tg_user_name TEXT,
            tg_user_date REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_data (
            user_id INTEGER NOT NULL,
            field TEXT NOT NULL,
            value TEXT,
            updated_at REAL,
            PRIMARY KEY (user_id, field)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_data_user ON user_data(user_id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            user_id INTEGER NOT NULL,
            event_time REAL NOT NULL,
            event_type TEXT,
            block_id TEXT,
            direction TEXT DEFAULT 'inbound'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_user_time ON activity_log(user_id, event_time)")
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
        if "block_id" not in cols:
            conn.execute("ALTER TABLE activity_log ADD COLUMN block_id TEXT")
        if "direction" not in cols:
            conn.execute("ALTER TABLE activity_log ADD COLUMN direction TEXT DEFAULT 'inbound'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_block ON activity_log(block_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_direction ON activity_log(direction)")
    except Exception:
        pass
    conn.commit()
    json_path = os.path.join(BASE_DIR, "user_data.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                old = json.load(f)
            import time as _t
            for uid, fields in old.items():
                if isinstance(fields, dict):
                    for k, v in fields.items():
                        conn.execute(
                            "INSERT OR REPLACE INTO user_data (user_id, field, value, updated_at) VALUES (?, ?, ?, ?)",
                            (int(uid), k, str(v) if v is not None else "", _t.time())
                        )
            conn.commit()
            conn.close()
            os.rename(json_path, json_path + ".bak")
        except Exception:
            conn.close()
    else:
        conn.close()

_init_user_db()

# In-memory cache of last reply keyboard layout (mirrors user_data.current_menu_id).
LAST_REPLY_KEYBOARD_FP = {}
CURRENT_MENU_FIELD = "current_menu_id"


def _reply_menu_signature(buttons):
    """Стабильная подпись набора кнопок reply-меню (как в блоке menu)."""
    if buttons and isinstance(buttons[0], str):
        buttons = [{"text": t} for t in buttons]
    rows = []
    for b in buttons or []:
        t = (b.get("text") if isinstance(b, dict) else str(b)) or "•"
        t = str(t)[:25]
        c = bool(isinstance(b, dict) and b.get("request_contact"))
        l = bool(isinstance(b, dict) and b.get("request_location"))
        rows.append({"text": t, "req_c": c, "req_l": l})
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def menu_layout_id(block_id: str, buttons, breaks=None) -> str:
    """Stable layout id for a menu block (block + button fingerprint + row breaks)."""
    count = len(buttons or [])
    br = normalize_button_row_breaks(breaks if breaks is not None else [0], count)
    br_sig = ",".join(str(x) for x in br)
    return f"{block_id}:{_reply_menu_signature(buttons)}:rows={br_sig}"


def get_current_menu_id(user_id: int):
    """Active ReplyKeyboard layout id for this user (from SQLite user_data)."""
    try:
        val = get_user_field(user_id, CURRENT_MENU_FIELD)
    except Exception:
        val = None
    if val is None or str(val).strip() == "":
        # Fallback to process-local cache
        return LAST_REPLY_KEYBOARD_FP.get(user_id)
    return str(val).strip()


def set_current_menu_id(user_id: int, menu_id: str | None):
    """Persist active ReplyKeyboard layout; None/empty = keyboard removed."""
    mid = (menu_id or "").strip()
    if mid:
        LAST_REPLY_KEYBOARD_FP[user_id] = mid
        try:
            set_user_field(user_id, CURRENT_MENU_FIELD, mid)
        except Exception:
            pass
    else:
        LAST_REPLY_KEYBOARD_FP.pop(user_id, None)
        try:
            set_user_field(user_id, CURRENT_MENU_FIELD, "")
        except Exception:
            pass


def _clear_last_reply_keyboard(chat_id: int, user_id: int = None):
    """Forget active reply keyboard (after ReplyKeyboardRemove or /start)."""
    LAST_REPLY_KEYBOARD_FP.pop(chat_id, None)
    if user_id is not None:
        LAST_REPLY_KEYBOARD_FP.pop(user_id, None)
        set_current_menu_id(user_id, None)


def resolve_reply_keyboard(user_id: int, target_menu_id: str | None, markup):
    """
    Conditional ReplyKeyboard attach:
    - same layout → omit reply_markup (Telegram keeps current keyboard static)
    - different layout → send markup and caller must persist target_menu_id
    - target_menu_id is None → ReplyKeyboardRemove
    Returns (reply_markup_or_None, should_update_state, new_menu_id).
    """
    current = get_current_menu_id(user_id)
    if target_menu_id is None:
        return ReplyKeyboardRemove(), True, None
    if current and current == target_menu_id:
        return None, False, current
    return markup, True, target_menu_id


def _msk_now_str():
    """Текущая дата/время в МСК."""
    import time
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")
    except Exception:
        from datetime import datetime
        return datetime.now().strftime("%d.%m.%Y %H:%M")


def ensure_user_registered(user_id: int, tg_username: str = None, tg_first_name: str = None):
    """Регистрирует пользователя при первом входе: tg_user_id, tg_user_name, tg_user_date.
    tg_user_date — дата регистрации в МСК. Записывает в user_data для {{tg_user_id}}, {{tg_user_name}}, {{tg_user_date}}."""
    import sqlite3
    import time
    now = time.time()
    msk_date = _msk_now_str()
    name = tg_username or tg_first_name or ""
    conn = sqlite3.connect(USER_DB_PATH)
    try:
        r = conn.execute("SELECT 1 FROM users WHERE tg_user_id = ?", (user_id,)).fetchone()
        if not r:
            conn.execute(
                "INSERT INTO users (tg_user_id, tg_user_name, tg_user_date) VALUES (?, ?, ?)",
                (user_id, name, now)
            )
            conn.execute(
                "INSERT OR REPLACE INTO user_data (user_id, field, value, updated_at) VALUES (?, 'tg_user_id', ?, ?)",
                (user_id, str(user_id), now)
            )
            conn.execute(
                "INSERT OR REPLACE INTO user_data (user_id, field, value, updated_at) VALUES (?, 'tg_user_name', ?, ?)",
                (user_id, name, now)
            )
            conn.execute(
                "INSERT OR REPLACE INTO user_data (user_id, field, value, updated_at) VALUES (?, 'tg_user_date', ?, ?)",
                (user_id, msk_date, now)
            )
            conn.commit()
    finally:
        conn.close()


def get_user_field(user_id: int, field: str):
    import sqlite3
    try:
        conn = sqlite3.connect(USER_DB_PATH)
        r = conn.execute(
            "SELECT value FROM user_data WHERE user_id = ? AND field = ?",
            (user_id, field)
        ).fetchone()
        conn.close()
        return r[0] if r else None
    except Exception:
        return None


def set_user_field(user_id: int, field: str, value):
    import sqlite3
    import time
    _init_user_db()
    conn = sqlite3.connect(USER_DB_PATH)
    conn.execute(
        """INSERT OR REPLACE INTO user_data (user_id, field, value, updated_at)
           VALUES (?, ?, ?, ?)""",
        (user_id, field, str(value) if value is not None else "", time.time())
    )
    conn.commit()
    conn.close()


def log_activity(user_id: int, event_type: str = "action", block_id: str = None, direction: str = "inbound"):
    """Persist an analytics event. direction: inbound (user) | flow (bot traversal) | outbound."""
    import sqlite3
    import time
    direction = (direction or "inbound").strip().lower() or "inbound"
    try:
        conn = sqlite3.connect(USER_DB_PATH)
        try:
            conn.execute(
                "INSERT INTO activity_log (user_id, event_time, event_type, block_id, direction) VALUES (?, ?, ?, ?, ?)",
                (user_id, time.time(), event_type, block_id, direction),
            )
        except sqlite3.OperationalError:
            try:
                conn.execute(
                    "INSERT INTO activity_log (user_id, event_time, event_type, block_id) VALUES (?, ?, ?, ?)",
                    (user_id, time.time(), event_type, block_id),
                )
            except sqlite3.OperationalError:
                et = event_type
                if block_id and not str(event_type).startswith(("block:", "visit:", "command:")):
                    et = f"block:{block_id}"
                conn.execute(
                    "INSERT INTO activity_log (user_id, event_time, event_type) VALUES (?, ?, ?)",
                    (user_id, time.time(), et),
                )
        conn.commit()
        conn.close()
    except Exception:
        pass


def log_block_visit(user_id: int, block_id: str, event_type: str = "visit"):
    """Bot flow traversal — counted in interaction share, NOT in inbound messages."""
    if not block_id:
        return
    log_activity(user_id, event_type or "visit", block_id=str(block_id), direction="flow")


def log_user_command(user_id: int, command_text: str, block_id: str = None):
    """Slash-command interception: always write inbound + entry block when known."""
    cmd = (command_text or "").strip().lower()
    if not cmd:
        return
    if not cmd.startswith("/"):
        cmd = "/" + cmd
    # Keep event_type as start/command AND encode the slash name for analytics remap.
    et = "start" if cmd == "/start" else f"command:{cmd}"
    log_activity(user_id, et, block_id=str(block_id) if block_id else None, direction="inbound")


def get_all_user_fields(user_id: int) -> dict:
    import sqlite3
    try:
        conn = sqlite3.connect(USER_DB_PATH)
        rows = conn.execute(
            "SELECT field, value FROM user_data WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


def get_start_block_id():
    for b in SCENARIO.get("blocks", []):
        if b.get("type") == "start":
            return b.get("id")
    return None


def get_start_next():
    for b in SCENARIO.get("blocks", []):
        if b.get("type") == "start":
            return NEXT_MAP.get((b["id"], 0))
    return None


def get_next_block(block_id, output_index=0):
    if isinstance(output_index, str):
        output_index = int(output_index) if output_index.isdigit() else 0
    return NEXT_MAP.get((block_id, output_index))


def _fsm_resume_accept_input(origin_block_id, next_id) -> bool:
    """
    F2: only feed last_message_text into the NEXT node when it is a self-reentry
    (weather / svoy / ai_director / forward). After Data Input the downstream
    node must NOT see the just-saved text (cascade pollution).
    """
    if not next_id:
        return False
    return str(next_id) == str(origin_block_id or "")


async def handle_unwired_port(bot, chat_id, user_id, block_id, port_index, ctx=None):
    """
    F4/F5: branch/condition port with no outgoing edge.
    Log BB_RUNTIME_ERROR, notify the user — never silent-drop or clear FSM.
    """
    blk = BLOCKS_BY_ID.get(block_id) or {}
    typ = str(blk.get("type") or "")
    payload = {
        "bot_id": BOT_ID,
        "user_id": user_id,
        "failing_node_id": str(block_id or ""),
        "node_type": typ,
        "exception_type": "UnwiredPort",
        "stack_trace": "",
        "message": f"Port {port_index} has no outgoing connection on block {block_id}",
        "local_variables_snapshot": {
            "port_index": port_index,
            "ctx": _redact_runtime_value(
                {
                    k: (ctx or {}).get(k)
                    for k in (
                        "trigger_text",
                        "accept_input",
                        "force_await_input",
                        "input_origin_block",
                    )
                    if isinstance(ctx, dict)
                }
            ),
        },
    }
    try:
        log.error("BB_RUNTIME_ERROR:%s", json.dumps(payload, ensure_ascii=False))
    except Exception:
        log.warning("Unwired port %s on block %s (user=%s)", port_index, block_id, user_id)
    try:
        import urllib.request

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            API_SIDECAR + "/api/ai/runtime-errors",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=0.4)
    except Exception:
        pass
    try:
        await bot.send_message(
            chat_id,
            "Действие не настроено. Этот выход сценария не подключён. "
            "Обратитесь к администратору или отправьте /start.",
        )
    except Exception:
        pass
    return None


def _format_value_for_display(val: str) -> str:
    """Форматирование числа: 200.0 → 200, 200.1 → 200.1."""
    if val is None or val == "":
        return ""
    try:
        f = float(str(val).replace(",", "."))
        if f == int(f):
            return str(int(f))
        return str(f)
    except (ValueError, TypeError):
        return str(val)


def resolve_text(text: str, user_id: int) -> str:
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
    return result


__PLUGIN_HANDLER_DEFINITIONS__


async def execute_block(bot: Bot, chat_id: int, user_id: int, block_id: str, ctx: dict = None):
    """Выполнить блок: сообщение, меню, данные, условие. ctx: last_message_text для data.input."""
    ctx = ctx or {}
    block = BLOCKS_BY_ID.get(block_id)
    if not block:
        return
    typ = block.get("type")
    data = block.get("data") or {}
    _disable_raw = data.get("disableWebPagePreview", False)
    if isinstance(_disable_raw, bool):
        disable = _disable_raw
    elif _disable_raw in (None, {}, [], ""):
        disable = False
    else:
        disable = bool(_disable_raw)
    try:
        log_block_visit(user_id, block_id, "visit")
    except Exception:
        pass
    try:
        return await _dispatch_block(bot, chat_id, user_id, block_id, ctx, data, disable, typ)
    except Exception as _bb_exc:
        _report_node_runtime_error(user_id, block_id, typ, data, ctx, _bb_exc)
        try:
            await bot.send_message(
                chat_id,
                "Ошибка сценария: технический сбой в блоке ["
                + str(typ or block_id or "?")
                + "]. Отправьте /start или проверьте логи запуска.",
            )
        except Exception:
            pass
        return


async def _dispatch_block(bot, chat_id, user_id, block_id, ctx, data, disable, typ):
__PLUGIN_EXECUTE_DISPATCH__


async def _register_await_input(
    bot: Bot,
    chat_id: int,
    user_id: int,
    state: FSMContext,
    info: dict,
):
    """
    Persist FSM wait for a specific Input node. Re-entrant safe: loops that
    return to the same Wait/Input block re-register without wiping user_data.
    """
    blk = BLOCKS_BY_ID.get(info.get("block_id"))
    dd = (blk.get("data") or {}) if blk else {}
    prompt = (info.get("input_prompt") or dd.get("inputPrompt") or "").strip()
    skip_prompt = bool(info.get("skip_prompt"))
    pending = {
        "data_block_id": info["block_id"],
        "data_field": info["field"],
        "data_field_type": info.get("field_type", "string"),
        "data_next_id": info.get("next_id"),
    }
    had_reply_kb = bool(get_current_menu_id(user_id))
    # Re-attach wait handler for this user (loop-safe). Keep other FSM keys.
    await state.set_state(ScenarioState.awaiting_data_input)
    await state.update_data(**pending)
    save_pending_input(user_id, pending)
    _clear_last_reply_keyboard(chat_id, user_id=user_id)

    # Smart prompting: a Message node in the same tick already asked the user —
    # only register FSM, do not send a second prompt bubble.
    if skip_prompt:
        if had_reply_kb:
            # Strip reply keyboard without repeating the Message prompt text.
            try:
                await bot.send_message(
                    chat_id,
                    "\u2060",
                    reply_markup=ReplyKeyboardRemove(),
                )
            except Exception:
                pass
        return

    if prompt:
        msg_text = resolve_text(prompt, user_id)
    else:
        input_type = info.get("field_type", "string")
        msg_text = temporal_input_hint(input_type) or "Введите значение:"
    await bot.send_message(
        chat_id,
        msg_text,
        reply_markup=ReplyKeyboardRemove(),
    )


async def run_from_block(
    bot: Bot,
    chat_id: int,
    user_id: int,
    block_id: str,
    state: FSMContext,
    last_text: str = "",
    last_message_id: int | None = None,
    last_from_chat_id: int | None = None,
    *,
    accept_input: bool = False,
    input_origin_block: str | None = None,
):
    """
    Run the scenario chain starting at block_id.

    accept_input=False (default): transition was triggered by a button/callback/
    command — NEVER feed that trigger text into Wait/Input nodes. Input blocks
    must pause and wait for a *new* user event.

    accept_input=True: continuing after a completed FSM wait (e.g. weather /
    svoy_blok self-reentry) — last_text is the captured user value.
    Only pass accept_input=True when next_id == awaiting block (self-reentry).
    """
    block = BLOCKS_BY_ID.get(block_id)
    if not block:
        return
    typ = block.get("type")
    # Split trigger vs consumable input. Input nodes must not see button labels.
    # F2: when accept_input is False, last_message_text stays empty for downstream.
    ctx = {
        "last_message_text": last_text if accept_input else "",
        "trigger_text": last_text or "",
        "last_message_id": last_message_id if accept_input else None,
        "last_chat_id": last_from_chat_id if last_from_chat_id is not None else chat_id,
        "accept_input": bool(accept_input),
        "force_await_input": not bool(accept_input),
        "input_origin_block": (
            str(input_origin_block) if accept_input and input_origin_block else None
        ),
        "_tick_input_visits": [],
    }

    if typ == "menu":
        await execute_block(bot, chat_id, user_id, block_id, ctx)
        await state.set_state(ScenarioState.in_menu)
        await state.update_data(block_id=block_id)
        return

    if typ == "message":
        # F1: chain continue lives in _type_handler_message via execute_block.
        # Do not recurse here — that would double-fire the next node.
        result = await execute_block(bot, chat_id, user_id, block_id, ctx)
        if result and result[0] == "await_input":
            _, info = result
            await _register_await_input(bot, chat_id, user_id, state, info)
        elif result and result[0] == "entered_menu":
            await state.set_state(ScenarioState.in_menu)
            await state.update_data(block_id=result[1])
        return

    if typ not in ("menu", "message"):
        result = await execute_block(bot, chat_id, user_id, block_id, ctx)
        if result and result[0] == "await_input":
            _, info = result
            await _register_await_input(bot, chat_id, user_id, state, info)
            return
        if result and result[0] == "entered_menu":
            await state.set_state(ScenarioState.in_menu)
            await state.update_data(block_id=result[1])
            return
        return


async def restore_pending_input_state(state: FSMContext, user_id: int) -> bool:
    pending = load_pending_input(user_id)
    if not pending or not pending.get("data_field"):
        return False
    await state.set_state(ScenarioState.awaiting_data_input)
    await state.update_data(**pending)
    return True


def get_command_blocks():
    return [b for b in SCENARIO.get("blocks", []) if b.get("type") == "command"]


def get_all_menu_button_texts():
    """Тексты кнопок меню — для отмены ввода при нажатии кнопки."""
    texts = set()
    for b in SCENARIO.get("blocks", []):
        if b.get("type") != "menu":
            continue
        for btn in (b.get("data") or {}).get("buttons") or []:
            t = (btn.get("text") if isinstance(btn, dict) else btn) or ""
            if t.strip():
                texts.add(t.strip())
    return texts


def get_menu_block_and_index_for_button(button_text: str):
    """Возвращает (block_id, button_index) для первой найденной кнопки меню с таким текстом, иначе (None, None)."""
    t = (button_text or "").strip()
    if not t:
        return None, None
    for b in SCENARIO.get("blocks", []):
        if b.get("type") != "menu":
            continue
        btn_list = (b.get("data") or {}).get("buttons") or []
        if btn_list and isinstance(btn_list[0], str):
            btn_list = [{"text": x} for x in btn_list]
        for i, btn in enumerate(btn_list):
            b_text = (btn.get("text") if isinstance(btn, dict) else btn) or ""
            if b_text.strip() == t:
                return b["id"], i
    return None, None


def format_location_point(loc) -> str:
    """Широта и долгота одной строкой для user_data."""
    if not loc:
        return ""
    try:
        la = float(loc.latitude)
        lo = float(loc.longitude)
        return f"{la:.6f},{lo:.6f}"
    except (TypeError, ValueError, AttributeError):
        return ""


def normalize_temporal_value(value, field_type: str) -> str:
    """Normalize user-entered date/time to stable ISO-like strings."""
    from datetime import datetime

    raw = str(value or "").strip()
    if not raw:
        return ""
    normalized = raw.replace("T", " ").replace("/", ".")
    formats = {
        "date": ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y"),
        "time": ("%H:%M", "%H:%M:%S"),
        "datetime": (
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%d-%m-%Y %H:%M",
        ),
    }
    for fmt in formats.get(field_type, ()):
        try:
            parsed = datetime.strptime(normalized, fmt)
            if field_type == "date":
                return parsed.strftime("%Y-%m-%d")
            if field_type == "time":
                return parsed.strftime("%H:%M")
            return parsed.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return ""


def temporal_input_hint(field_type: str) -> str:
    if field_type == "date":
        return "Введите дату в формате ДД.ММ.ГГГГ."
    if field_type == "time":
        return "Введите время в формате ЧЧ:ММ."
    if field_type == "datetime":
        return "Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ."
    return ""


@dp.message(F.text.in_({"/start", "/Start"}))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id if message.from_user else 0
    clear_pending_input(user_id)
    _clear_last_reply_keyboard(message.chat.id, user_id=user_id)
    username = (message.from_user.username or message.from_user.first_name or "") if message.from_user else ""
    ensure_user_registered(user_id, tg_username=message.from_user.username if message.from_user else None,
                          tg_first_name=message.from_user.first_name if message.from_user else None)
    start_block_id = get_start_block_id()
    log_user_command(user_id, "/start", block_id=start_block_id)
    next_id = get_start_next()
    if next_id:
        await run_from_block(bot, message.chat.id, user_id, next_id, state)
    else:
        await message.answer("Добро пожаловать! Настройте сценарий в редакторе.")


COMMAND_TO_BLOCK = {}
COMMAND_ENTRY_BLOCK = {}
for cmd_block in get_command_blocks():
    cmd_text = (cmd_block.get("data") or {}).get("command", "/help").strip().lower()
    if not cmd_text.startswith("/"):
        cmd_text = "/" + cmd_text
    next_id = get_next_block(cmd_block["id"], 0)
    entry_id = cmd_block.get("id")
    COMMAND_TO_BLOCK[cmd_text] = next_id
    COMMAND_TO_BLOCK[cmd_text.capitalize()] = next_id
    COMMAND_ENTRY_BLOCK[cmd_text] = entry_id
    COMMAND_ENTRY_BLOCK[cmd_text.capitalize()] = entry_id


@dp.callback_query(F.data.startswith("__bb_nolink:"))
async def on_unlinked_inline(callback: types.CallbackQuery):
    await callback.answer("Кнопка не подключена в сценарии", show_alert=True)


@dp.callback_query(F.data)
async def on_inline(callback: types.CallbackQuery, state: FSMContext):
    block_id = callback.data
    if block_id.startswith("__appt:"):
        parts = block_id.split(":", 2)
        if len(parts) != 3:
            await callback.answer("Некорректная заявка", show_alert=True)
            return
        action, appointment_id = parts[1], parts[2]
        admin_user_id = callback.from_user.id if callback.from_user else 0
        current_chat = str(callback.message.chat.id) if callback.message else ""
        if not is_appointment_moderator(admin_user_id, current_chat):
            await callback.answer("Недостаточно прав", show_alert=True)
            return
        status = "accepted" if action == "accept" else "rejected"
        appointment = get_appointment(appointment_id)
        if not appointment:
            await callback.answer("Заявка не найдена", show_alert=True)
            return
        if not update_appointment_status(
            appointment_id,
            status,
            moderator_id=admin_user_id,
        ):
            await callback.answer("Заявка уже обработана", show_alert=True)
            return
        status_text = "Принята" if status == "accepted" else "Отклонена"
        await callback.answer(status_text)
        if callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
                await callback.message.answer(
                    f"{status_text}: заявка №{appointment_id}"
                )
            except Exception:
                pass
        user_message = (
            f"Ваша заявка №{appointment_id} подтверждена."
            if status == "accepted"
            else f"Ваша заявка №{appointment_id} отклонена."
        )
        try:
            await bot.send_message(int(appointment["user_id"]), user_message)
        except Exception:
            pass
        return
    await callback.answer()
    if block_id not in BLOCKS_BY_ID:
        return
    user_id = callback.from_user.id if callback.from_user else 0
    ensure_user_registered(user_id,
        tg_username=callback.from_user.username if callback.from_user else None,
        tg_first_name=callback.from_user.first_name if callback.from_user else None)
    # Inbound click attributed to the target block (heatmap share).
    log_activity(user_id, "callback", block_id=str(block_id), direction="inbound")
    await run_from_block(bot, callback.message.chat.id, user_id, block_id, state)


@dp.message(ScenarioState.awaiting_data_input, F.contact)
async def on_awaiting_data_contact(message: types.Message, state: FSMContext):
    """Контакт при ожидании ввода — сохраняем номер телефона в текущее поле."""
    user_id = message.from_user.id if message.from_user else 0
    phone = (message.contact.phone_number if message.contact else "") or ""
    data = await state.get_data()
    field = data.get("data_field", "")
    next_id = data.get("data_next_id")
    if not field:
        await state.clear()
        clear_pending_input(user_id)
        return
    apply_scoped_field_value(user_id, field, phone)
    await state.clear()
    clear_pending_input(user_id)
    if next_id:
        # F2: clear consumable input for downstream; self-reentry keeps accept_input.
        origin = data.get("data_block_id") or ""
        resume_accept = _fsm_resume_accept_input(origin, next_id)
        await run_from_block(
            bot,
            message.chat.id,
            user_id,
            next_id,
            state,
            phone if resume_accept else "",
            last_message_id=message.message_id if resume_accept else None,
            last_from_chat_id=message.chat.id,
            accept_input=resume_accept,
            input_origin_block=origin if resume_accept else None,
        )
    else:
        await message.answer("Данные сохранены.")


@dp.message(ScenarioState.awaiting_data_input, F.location)
async def on_awaiting_data_location(message: types.Message, state: FSMContext):
    """Геолокация при ожидании ввода — сохраняем \"широта,долгота\" в поле."""
    user_id = message.from_user.id if message.from_user else 0
    loc = message.location
    val = format_location_point(loc)
    data = await state.get_data()
    field = data.get("data_field", "")
    next_id = data.get("data_next_id")
    if not field:
        await state.clear()
        clear_pending_input(user_id)
        return
    apply_scoped_field_value(user_id, field, val)
    await state.clear()
    clear_pending_input(user_id)
    if next_id:
        origin = data.get("data_block_id") or ""
        resume_accept = _fsm_resume_accept_input(origin, next_id)
        await run_from_block(
            bot,
            message.chat.id,
            user_id,
            next_id,
            state,
            val if resume_accept else "",
            last_message_id=message.message_id if resume_accept else None,
            last_from_chat_id=message.chat.id,
            accept_input=resume_accept,
            input_origin_block=origin if resume_accept else None,
        )
    else:
        await message.answer("Данные сохранены.")


@dp.message(ScenarioState.awaiting_data_input, F.text)
async def on_awaiting_data_input(message: types.Message, state: FSMContext):
    """Обработка ввода пользователя при ожидании данных (valueSource=input)."""
    user_id = message.from_user.id if message.from_user else 0
    txt = (message.text or "").strip()
    data = await state.get_data()
    data_block_id = data.get("data_block_id") or ""

    def _clear_forward_pending():
        if data_block_id:
            set_user_field(user_id, f"_fwd_pending_{data_block_id}", "")

    if txt.lower() == "/start":
        clear_pending_input(user_id)
        await cmd_start(message, state)
        return
    if txt.startswith("/"):
        _clear_forward_pending()
        await state.clear()
        clear_pending_input(user_id)
        await message.answer("Действие отменено.")
        return
    menu_texts = get_all_menu_button_texts()
    if txt in menu_texts:
        _clear_forward_pending()
        await state.clear()
        clear_pending_input(user_id)
        await message.answer("Действие отменено. Нажатие кнопки меню прервало ввод.")
        return
    field = data.get("data_field", "")
    field_type = data.get("data_field_type", "string")
    next_id = data.get("data_next_id")
    if field_type == "number":
        try:
            val = str(float(txt.replace(",", ".")))
        except (ValueError, TypeError):
            await message.answer("Введите число.")
            return
    elif field_type in ("date", "time", "datetime"):
        val = normalize_temporal_value(txt, field_type)
        if not val:
            await message.answer(temporal_input_hint(field_type))
            return
    else:
        val = txt
    apply_scoped_field_value(user_id, field, val)
    # Clear wait BEFORE continuing; if the graph loops back to an Input node,
    # run_from_block will re-register awaiting_data_input for this user.
    await state.clear()
    clear_pending_input(user_id)
    if next_id:
        # F2: Data Input already persisted the value. Downstream nodes must NOT
        # see last_message_text unless this is a self-reentry (weather/svoy/ai).
        origin = data_block_id
        resume_accept = _fsm_resume_accept_input(origin, next_id)
        await run_from_block(
            bot,
            message.chat.id,
            user_id,
            next_id,
            state,
            txt if resume_accept else "",
            last_message_id=message.message_id if resume_accept else None,
            last_from_chat_id=message.chat.id,
            accept_input=resume_accept,
            input_origin_block=origin if resume_accept else None,
        )
    else:
        await message.answer("Данные сохранены.")


@dp.message(ScenarioState.awaiting_data_input)
async def on_awaiting_data_unsupported(message: types.Message):
    """Keep the pending FSM state and explain accepted input kinds."""
    await message.answer(
        "Отправьте текст, контакт или геопозицию. "
        "Для отмены отправьте команду, например /start."
    )


@dp.callback_query(ScenarioState.awaiting_data_input, F.data)
async def on_callback_while_awaiting_input(callback: types.CallbackQuery, state: FSMContext):
    """Отмена ввода при нажатии inline-кнопки."""
    await callback.answer()
    data = await state.get_data()
    data_block_id = data.get("data_block_id") or ""
    user_id = callback.from_user.id if callback.from_user else 0
    if data_block_id and user_id:
        set_user_field(user_id, f"_fwd_pending_{data_block_id}", "")
    clear_pending_input(user_id)
    await state.clear()
    await callback.message.answer("Действие отменено.")


@dp.message(ScenarioState.in_menu, F.text)
async def on_menu_choice(message: types.Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    last_text = (message.text or "").strip()
    if not _claim_inbound_event(user_id, message.message_id, last_text):
        return
    ensure_user_registered(user_id,
        tg_username=message.from_user.username if message.from_user else None,
        tg_first_name=message.from_user.first_name if message.from_user else None)
    data = await state.get_data()
    block_id = data.get("block_id")
    block = BLOCKS_BY_ID.get(block_id) if block_id else None
    if not block or block.get("type") != "menu":
        await state.clear()
        return
    buttons = block.get("data") or {}
    btn_list = buttons.get("buttons") or []
    if btn_list and isinstance(btn_list[0], str):
        btn_list = [{"text": t} for t in btn_list]
    # Ignore Telegram system "Главное меню"
    if last_text.lower().rstrip(":") in ("главное меню", "main menu"):
        return
    for i, btn in enumerate(btn_list):
        b_text = (btn.get("text") if isinstance(btn, dict) else btn) or ""
        if last_text == b_text.strip():
            # Attribute click to the button name, not the whole menu / message text
            log_activity(
                user_id,
                f"button:{last_text}",
                block_id=f"{block_id}#{i}",
                direction="inbound",
            )
            next_id = get_next_block(block_id, i)
            if next_id:
                await run_from_block(
                    bot,
                    message.chat.id,
                    user_id,
                    next_id,
                    state,
                    last_text,
                    last_message_id=message.message_id,
                    last_from_chat_id=message.chat.id,
                )
            else:
                await state.clear()
            return
    await state.clear()


@dp.message(ScenarioState.in_menu, F.contact)
async def on_menu_contact(message: types.Message, state: FSMContext):
    """Кнопка «Поделиться контактом» в reply-меню."""
    user_id = message.from_user.id if message.from_user else 0
    ensure_user_registered(user_id,
        tg_username=message.from_user.username if message.from_user else None,
        tg_first_name=message.from_user.first_name if message.from_user else None)
    log_activity(user_id, "menu_contact")
    data = await state.get_data()
    block_id = data.get("block_id")
    block = BLOCKS_BY_ID.get(block_id) if block_id else None
    if not block or block.get("type") != "menu":
        await state.clear()
        return
    buttons = block.get("data") or {}
    btn_list = buttons.get("buttons") or []
    if btn_list and isinstance(btn_list[0], str):
        btn_list = [{"text": t} for t in btn_list]
    phone = (message.contact.phone_number if message.contact else "") or ""
    for i, btn in enumerate(btn_list):
        if isinstance(btn, dict) and btn.get("request_contact"):
            next_id = get_next_block(block_id, i)
            await state.clear()
            if not next_id:
                return
            nblock = BLOCKS_BY_ID.get(next_id)
            if nblock and nblock.get("type") == "data":
                dd = nblock.get("data") or {}
                fn = (dd.get("fieldName") or "").strip() or "phone"
                apply_scoped_field_value(user_id, fn, phone)
                nn = get_next_block(next_id, 0)
                if nn:
                    await run_from_block(
                        bot,
                        message.chat.id,
                        user_id,
                        nn,
                        state,
                        phone,
                        last_message_id=message.message_id,
                        last_from_chat_id=message.chat.id,
                    )
            else:
                await run_from_block(
                    bot,
                    message.chat.id,
                    user_id,
                    next_id,
                    state,
                    phone,
                    last_message_id=message.message_id,
                    last_from_chat_id=message.chat.id,
                )
            return
    await state.clear()


@dp.message(ScenarioState.in_menu, F.location)
async def on_menu_location(message: types.Message, state: FSMContext):
    """Кнопка «Отправить геолокацию» в reply-меню."""
    user_id = message.from_user.id if message.from_user else 0
    ensure_user_registered(user_id,
        tg_username=message.from_user.username if message.from_user else None,
        tg_first_name=message.from_user.first_name if message.from_user else None)
    log_activity(user_id, "menu_location")
    data = await state.get_data()
    block_id = data.get("block_id")
    block = BLOCKS_BY_ID.get(block_id) if block_id else None
    if not block or block.get("type") != "menu":
        await state.clear()
        return
    buttons = block.get("data") or {}
    btn_list = buttons.get("buttons") or []
    if btn_list and isinstance(btn_list[0], str):
        btn_list = [{"text": t} for t in btn_list]
    loc_val = format_location_point(message.location)
    for i, btn in enumerate(btn_list):
        if isinstance(btn, dict) and btn.get("request_location"):
            next_id = get_next_block(block_id, i)
            await state.clear()
            if not next_id:
                return
            nblock = BLOCKS_BY_ID.get(next_id)
            if nblock and nblock.get("type") == "data":
                dd = nblock.get("data") or {}
                fn = (dd.get("fieldName") or "").strip() or "location"
                apply_scoped_field_value(user_id, fn, loc_val)
                nn = get_next_block(next_id, 0)
                if nn:
                    await run_from_block(
                        bot,
                        message.chat.id,
                        user_id,
                        nn,
                        state,
                        loc_val,
                        last_message_id=message.message_id,
                        last_from_chat_id=message.chat.id,
                    )
            else:
                await run_from_block(
                    bot,
                    message.chat.id,
                    user_id,
                    next_id,
                    state,
                    loc_val,
                    last_message_id=message.message_id,
                    last_from_chat_id=message.chat.id,
                )
            return
    await state.clear()


@dp.message(F.contact)
async def on_contact_without_state(message: types.Message, state: FSMContext):
    """Resume persisted Data input after a hot reload."""
    user_id = message.from_user.id if message.from_user else 0
    if await restore_pending_input_state(state, user_id):
        await on_awaiting_data_contact(message, state)
        return
    await message.answer("Сейчас бот не ожидает контакт. Отправьте /start.")


@dp.message(F.location)
async def on_location_without_state(message: types.Message, state: FSMContext):
    """Resume persisted Data input after a hot reload."""
    user_id = message.from_user.id if message.from_user else 0
    if await restore_pending_input_state(state, user_id):
        await on_awaiting_data_location(message, state)
        return
    await message.answer("Сейчас бот не ожидает геопозицию. Отправьте /start.")


@dp.message(F.text)
async def on_text_message(message: types.Message, state: FSMContext):
    # Defensive fallback: imported/legacy scenarios may reach the generic text
    # handler while an input field is pending. Never lose that user value.
    current_state = await state.get_state()
    pending = await state.get_data()
    user_id = message.from_user.id if message.from_user else 0
    txt = (message.text or "").strip()

    # in_menu is owned exclusively by on_menu_choice — never run a parallel path.
    if current_state == ScenarioState.in_menu.state:
        return

    if not pending.get("data_field"):
        restored = await restore_pending_input_state(state, user_id)
        if restored:
            current_state = await state.get_state()
            pending = await state.get_data()
    if (
        current_state == ScenarioState.awaiting_data_input.state
        or pending.get("data_field")
    ):
        await on_awaiting_data_input(message, state)
        return

    if not _claim_inbound_event(user_id, message.message_id, txt):
        return

    ensure_user_registered(user_id,
        tg_username=message.from_user.username if message.from_user else None,
        tg_first_name=message.from_user.first_name if message.from_user else None)
    txt_key = txt.lower() if txt.startswith("/") else txt

    # Slash commands: always log inbound + entry-node block_id (fixes 0% heatmap).
    if txt.startswith("/"):
        entry_id = COMMAND_ENTRY_BLOCK.get(txt) or COMMAND_ENTRY_BLOCK.get(txt_key)
        if txt_key in ("/start",):
            entry_id = entry_id or get_start_block_id()
        log_user_command(user_id, txt_key, block_id=entry_id)
        next_id = COMMAND_TO_BLOCK.get(txt) or COMMAND_TO_BLOCK.get(txt_key)
        if next_id is not None:
            await state.clear()
            if next_id:
                await run_from_block(bot, message.chat.id, user_id, next_id, state)
            else:
                await message.answer("Команда не настроена.")
            return
        # Unknown slash command still counted as inbound text/command.
        return

    log_activity(user_id, "text", direction="inbound")
    next_id = COMMAND_TO_BLOCK.get(txt)
    if next_id is not None:
        await state.clear()
        uid = message.from_user.id if message.from_user else 0
        entry_id = COMMAND_ENTRY_BLOCK.get(txt)
        if entry_id:
            log_activity(uid, "command", block_id=str(entry_id), direction="inbound")
        if next_id:
            await run_from_block(bot, message.chat.id, uid, next_id, state)
        else:
            await message.answer("Команда не настроена.")
    else:
        menu_block_id, menu_idx = get_menu_block_and_index_for_button(txt)
        if menu_block_id is not None and menu_idx is not None:
            if txt.lower().rstrip(":") not in ("главное меню", "main menu"):
                log_activity(
                    user_id,
                    f"button:{txt}",
                    block_id=f"{menu_block_id}#{menu_idx}",
                    direction="inbound",
                )
            next_id = get_next_block(menu_block_id, menu_idx)
            await state.set_state(ScenarioState.in_menu)
            await state.update_data(block_id=menu_block_id)
            if next_id:
                await run_from_block(
                    bot,
                    message.chat.id,
                    user_id,
                    next_id,
                    state,
                    txt,
                    last_message_id=message.message_id,
                    last_from_chat_id=message.chat.id,
                )
            else:
                await state.clear()
        else:
            await message.answer('Отправьте /start для начала.')


async def main():
    log.info("Connecting to Telegram API...")
    try:
        me = await asyncio.wait_for(bot.get_me(), timeout=45.0)
    except asyncio.TimeoutError:
        log.error(
            "Таймаут подключения к Telegram API (45с). "
            "Проверьте доступ api.telegram.org с сервера или укажите proxy в config.json"
        )
        raise SystemExit(1)
    log.info("Start polling as @%s (id=%s)", me.username, me.id)
    try:
        await dp.start_polling(bot)
    finally:
        await _bb_shutdown(bot)


async def _bb_shutdown(bot_obj=None):
    import inspect
    import sys

    for name, mod in list(sys.modules.items()):
        if not str(name).startswith("bb_app_"):
            continue
        fn = getattr(mod, "stop", None) or getattr(mod, "shutdown", None)
        if not callable(fn):
            continue
        try:
            if inspect.iscoroutinefunction(fn):
                await fn()
            else:
                fn()
        except Exception:
            log.exception("app shutdown failed: %s", name)
    try:
        if bot_obj is not None:
            await bot_obj.session.close()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as exc:
        log.exception("Bot stopped: %s", exc)
        raise
'''


def _copy_scenario_plugin_assets(bot_path: str, scenario: dict) -> None:
    """Copy image assets from plugins used in the scenario into bot media/."""
    import shutil

    from backend.core.plugin_manager import get_plugin_manager

    media_dir = os.path.join(bot_path, "media")
    os.makedirs(media_dir, exist_ok=True)
    mgr = get_plugin_manager()
    seen: set[str] = set()
    for block in scenario.get("blocks") or []:
        typ = str(block.get("type") or "")
        if not typ or typ in seen:
            continue
        seen.add(typ)
        plugin = mgr.get_by_type(typ)
        if not plugin:
            continue
        assets = plugin.path / "assets"
        if not assets.is_dir():
            continue
        for src in assets.iterdir():
            if not src.is_file():
                continue
            if src.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                continue
            dest = os.path.join(media_dir, f"{plugin.id}_{src.name}")
            try:
                shutil.copy2(src, dest)
            except OSError:
                pass


def generate_main_from_scenario(bot_id: int, platform: str | None = None) -> bool:
    """Генерирует main.py из scenario.json через plugin compiler."""
    if get_bot_kind(bot_id) == "moderator":
        return generate_moderator_main(bot_id)

    from backend.core.compiler import CodeGenerator

    bot_path = os.path.join(BASE_DIR, f"bot_{bot_id}")
    os.makedirs(bot_path, exist_ok=True)
    # Ensure scripts/ exists for app_bridge standalone apps
    os.makedirs(os.path.join(bot_path, "scripts"), exist_ok=True)

    if platform is None:
        platform = get_bot_platform(bot_id)
    platform = "telegram"

    scenario_path = os.path.join(bot_path, "scenario.json")
    scenario: dict = {"blocks": [], "connections": [], "tags": []}
    if os.path.exists(scenario_path):
        try:
            with open(scenario_path, "r", encoding="utf-8") as f:
                scenario = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    try:
        code = CodeGenerator().build_python_script(
            scenario,
            SCENARIO_MAIN_TEMPLATE,
            platform="telegram",
        )
    except TemplateSyntaxError as exc:
        # Last-resort: do not abort the whole save with an unhandled alert
        block_hint = getattr(exc, "name", None) or getattr(exc, "filename", None) or "unknown"
        _compile_log.error(
            "Jinja TemplateSyntaxError while compiling bot_%s (template=%s): %s",
            bot_id,
            block_hint,
            exc,
        )
        # Retry with plugin stubs already handled inside PluginManager; if shell
        # itself failed, re-raise a clear RuntimeError (still caught by API layer).
        raise RuntimeError(
            f"Scenario compile failed for block/template '{block_hint}': {exc}"
        ) from exc

    _validate_generated_bot_main(code)

    main_path = os.path.join(bot_path, "main.py")
    with open(main_path, "w", encoding="utf-8") as f:
        f.write(code)
    # Ensure config.json carries bot_id for telemetry
    try:
        cfg_path = os.path.join(bot_path, "config.json")
        if os.path.isfile(cfg_path):
            with open(cfg_path, encoding="utf-8") as cf:
                cfg = json.load(cf)
            if not isinstance(cfg, dict):
                cfg = {}
            if cfg.get("bot_id") != bot_id:
                cfg["bot_id"] = bot_id
                with open(cfg_path, "w", encoding="utf-8") as cf:
                    json.dump(cfg, cf, ensure_ascii=False, indent=2)
    except Exception:
        pass
    try:
        _copy_scenario_plugin_assets(bot_path, scenario)
    except Exception:
        pass
    return True


def _validate_generated_bot_main(code: str) -> None:
    """Ensure compiled bot runtime includes helpers referenced by plugin handlers."""
    if "build_button_rows_from_breaks(" in code and "def build_button_rows_from_breaks" not in code:
        raise RuntimeError(
            "Compiled main.py calls build_button_rows_from_breaks but the helper is missing. "
            "Update BotBuilder and re-save the scenario."
        )


def recompile_all_project_bots() -> int:
    """Regenerate main.py for every bot_* folder that has scenario.json."""
    if not os.path.isdir(BASE_DIR):
        return 0
    count = 0
    for name in sorted(os.listdir(BASE_DIR)):
        if not name.startswith("bot_"):
            continue
        try:
            bot_id = int(name.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        scenario_path = os.path.join(BASE_DIR, name, "scenario.json")
        if not os.path.isfile(scenario_path):
            continue
        try:
            generate_main_from_scenario(bot_id)
            count += 1
        except Exception:
            pass
    return count


# --- Старый шаблон (FSM/handlers/keyboard) — для обратной совместимости ---
TEMPLATE = """
import asyncio
import json
import os
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

BASE_DIR = os.path.dirname(__file__)

# Загрузка config.json (api_key или token)
with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
    config = json.load(f)
token = config.get("api_key") or config.get("token") or ""

bot = Bot(
    token=token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# --- FSM: динамические состояния из fsm.json ---
class DynamicStates(StatesGroup):
    pass

fsm_data = {}
fsm_path = os.path.join(BASE_DIR, "fsm.json")
if os.path.exists(fsm_path):
    with open(fsm_path, "r", encoding="utf-8") as f:
        fsm_data = json.load(f)

    for state_def in fsm_data.get("states", []):
        state_name = state_def["name"]
        setattr(DynamicStates, state_name, State())

# --- Загрузка клавиатур ---
reply_markup = None
inline_markup = None

keyboard_path = os.path.join(BASE_DIR, "keyboard.json")
if os.path.exists(keyboard_path):
    with open(keyboard_path, "r", encoding="utf-8") as f:
        keyboard_data = json.load(f)

    if keyboard_data.get("reply"):
        reply_markup = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=text) for text in row]
                for row in keyboard_data["reply"]
            ],
            resize_keyboard=True
        )

    if keyboard_data.get("inline"):
        inline_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"]) for btn in row]
                for row in keyboard_data["inline"]
            ]
        )

# --- Команды из handlers.json ---
handlers_path = os.path.join(BASE_DIR, "handlers.json")
if os.path.exists(handlers_path):
    with open(handlers_path, "r", encoding="utf-8") as f:
        handlers_data = json.load(f)

    for cmd in handlers_data.get("commands", []):
        command_text = cmd.get("text", "").lstrip("/")
        response_text = cmd.get("reply", "")

        @dp.message(lambda message, t=command_text: message.text and message.text.strip() == f"/{t}")
        async def handler(message: types.Message, r=response_text, t=command_text):
            uid = message.from_user.id if message.from_user else 0
            ensure_user_registered(
                uid,
                tg_username=message.from_user.username if message.from_user else None,
                tg_first_name=message.from_user.first_name if message.from_user else None,
            )
            entry = COMMAND_ENTRY_BLOCK.get("/" + t.lower()) or COMMAND_ENTRY_BLOCK.get(t.lower())
            log_user_command(uid, "/" + t.lower(), block_id=entry)
            await message.answer(r, reply_markup=reply_markup or inline_markup)

# --- FSM + универсальный обработчик ---
@dp.message()
async def universal_handler(message: types.Message, state: FSMContext):
    current = await state.get_state()

    if current:
        for state_def in fsm_data.get("states", []):
            if current.endswith(state_def["name"]):
                for tr in state_def.get("transitions", []):
                    await message.answer(tr["text"])
                    target = tr.get("target")
                    if target:
                        await state.set_state(getattr(DynamicStates, target, None))
                    else:
                        await state.clear()
                    return
    else:
        for state_def in fsm_data.get("states", []):
            if message.text.strip().lower() == state_def["name"].lower():
                await message.answer(state_def["message"])
                await state.set_state(getattr(DynamicStates, state_def["name"]))
                return

# --- Inline-кнопки ---
@dp.callback_query()
async def on_callback(callback: types.CallbackQuery):
    await callback.answer(f"Нажата кнопка: {callback.data}", show_alert=True)

# --- Запуск ---
async def main():
    import logging
    import socket
    import sys
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiohttp import ClientSession, TCPConnector

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    class ProxyAwareSession(AiohttpSession):
        async def create_session(self) -> ClientSession:
            if self._should_reset_connector:
                await self.close()
            if self._session is None or self._session.closed:
                self._session = ClientSession(
                    connector=TCPConnector(family=socket.AF_INET, limit=100),
                    trust_env=True,
                )
                self._should_reset_connector = False
            return self._session

    global bot
    bot = Bot(
        token=token,
        session=ProxyAwareSession(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    me = await bot.get_me()
    print(f"Start polling as @{me.username}")
    try:
        await dp.start_polling(bot)
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass

"""


def generate_main_py(bot_id: int):
    """Генерирует main.py: при наличии scenario.json — по сценарию, иначе — по FSM/handlers."""
    bot_path = os.path.join(BASE_DIR, f"bot_{bot_id}")
    os.makedirs(bot_path, exist_ok=True)

    if get_bot_kind(bot_id) == "moderator":
        return generate_moderator_main(bot_id)

    scenario_path = os.path.join(bot_path, "scenario.json")
    if os.path.exists(scenario_path):
        return generate_main_from_scenario(bot_id)

    code = Template(TEMPLATE).render()
    with open(os.path.join(bot_path, "main.py"), "w", encoding="utf-8") as f:
        f.write(code)
