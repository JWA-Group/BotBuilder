import os
import json
from jinja2 import Template

from backend.core.app_paths import PROJECTS_DIR as BASE_DIR


def get_bot_platform(bot_id: int) -> str:
    """Платформа бота: только telegram."""
    return "telegram"

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
        out = int(out) if out.isdigit() else 0
    NEXT_MAP[(c["from"], out)] = c["to"]


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

__PLUGIN_EXECUTE_DISPATCH__


async def run_from_block(
    bot: Bot,
    chat_id: int,
    user_id: int,
    block_id: str,
    state: FSMContext,
    last_text: str = "",
    last_message_id: int | None = None,
    last_from_chat_id: int | None = None,
):
    """Запуск цепочки с блока. Для menu — только показать, не продолжать."""
    block = BLOCKS_BY_ID.get(block_id)
    if not block:
        return
    typ = block.get("type")
    ctx = {
        "last_message_text": last_text,
        "last_message_id": last_message_id,
        "last_chat_id": last_from_chat_id if last_from_chat_id is not None else chat_id,
    }

    if typ == "menu":
        await execute_block(bot, chat_id, user_id, block_id, ctx)
        await state.set_state(ScenarioState.in_menu)
        await state.update_data(block_id=block_id)
        return

    if typ == "message":
        await execute_block(bot, chat_id, user_id, block_id, ctx)
        msg_data = block.get("data") or {}
        if msg_data.get("inlineButtons"):
            return
        next_id = get_next_block(block_id, 0)
        if next_id:
            await run_from_block(
                bot,
                chat_id,
                user_id,
                next_id,
                state,
                last_text,
                last_message_id=last_message_id,
                last_from_chat_id=last_from_chat_id,
            )
    elif typ not in ("menu", "message"):
        result = await execute_block(bot, chat_id, user_id, block_id, ctx)
        if result and result[0] == "await_input":
            _, info = result
            blk = BLOCKS_BY_ID.get(info["block_id"])
            dd = (blk.get("data") or {}) if blk else {}
            prompt = (info.get("input_prompt") or dd.get("inputPrompt") or "").strip()
            if prompt:
                msg_text = resolve_text(prompt, user_id)
            else:
                msg_text = " "
            await state.set_state(ScenarioState.awaiting_data_input)
            await state.update_data(
                data_block_id=info["block_id"],
                data_field=info["field"],
                data_field_type=info.get("field_type", "string"),
                data_next_id=info.get("next_id"),
            )
            _clear_last_reply_keyboard(chat_id, user_id=user_id)
            await bot.send_message(
                chat_id,
                msg_text,
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        return


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


@dp.message(F.text.in_({"/start", "/Start"}))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id if message.from_user else 0
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
        return
    set_user_field(user_id, field, phone)
    await state.clear()
    if next_id:
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
        return
    set_user_field(user_id, field, val)
    await state.clear()
    if next_id:
        await run_from_block(
            bot,
            message.chat.id,
            user_id,
            next_id,
            state,
            val,
            last_message_id=message.message_id,
            last_from_chat_id=message.chat.id,
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

    if txt.startswith("/"):
        _clear_forward_pending()
        await state.clear()
        await message.answer("Действие отменено.")
        return
    menu_texts = get_all_menu_button_texts()
    if txt in menu_texts:
        _clear_forward_pending()
        await state.clear()
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
    else:
        val = txt
    set_user_field(user_id, field, val)
    await state.clear()
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
        await message.answer("Данные сохранены.")


@dp.callback_query(ScenarioState.awaiting_data_input, F.data)
async def on_callback_while_awaiting_input(callback: types.CallbackQuery, state: FSMContext):
    """Отмена ввода при нажатии inline-кнопки."""
    await callback.answer()
    data = await state.get_data()
    data_block_id = data.get("data_block_id") or ""
    user_id = callback.from_user.id if callback.from_user else 0
    if data_block_id and user_id:
        set_user_field(user_id, f"_fwd_pending_{data_block_id}", "")
    await state.clear()
    await callback.message.answer("Действие отменено.")


@dp.message(ScenarioState.in_menu, F.text)
async def on_menu_choice(message: types.Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
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
    user_id = message.from_user.id if message.from_user else 0
    last_text = (message.text or "").strip()
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
                set_user_field(user_id, fn, phone)
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
                set_user_field(user_id, fn, loc_val)
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


@dp.message(F.text)
async def on_text_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    ensure_user_registered(user_id,
        tg_username=message.from_user.username if message.from_user else None,
        tg_first_name=message.from_user.first_name if message.from_user else None)
    txt = (message.text or "").strip()
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
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
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
    from backend.core.compiler import CodeGenerator

    bot_path = os.path.join(BASE_DIR, f"bot_{bot_id}")
    os.makedirs(bot_path, exist_ok=True)

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

    code = CodeGenerator().build_python_script(
        scenario,
        SCENARIO_MAIN_TEMPLATE,
        platform="telegram",
    )

    _validate_generated_bot_main(code)

    main_path = os.path.join(bot_path, "main.py")
    with open(main_path, "w", encoding="utf-8") as f:
        f.write(code)
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
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

"""


def generate_main_py(bot_id: int):
    """Генерирует main.py: при наличии scenario.json — по сценарию, иначе — по FSM/handlers."""
    bot_path = os.path.join(BASE_DIR, f"bot_{bot_id}")
    os.makedirs(bot_path, exist_ok=True)

    scenario_path = os.path.join(bot_path, "scenario.json")
    if os.path.exists(scenario_path):
        return generate_main_from_scenario(bot_id)

    code = Template(TEMPLATE).render()
    with open(os.path.join(bot_path, "main.py"), "w", encoding="utf-8") as f:
        f.write(code)
