# VK-бот: Long Poll API + aiohttp (без vkbottle — совместимо с aiogram/pydantic).

SCENARIO_VK_MAIN_TEMPLATE = '''# -*- coding: utf-8 -*-
"""Бот сообщества VK: Long Poll, сценарий scenario.json."""
import asyncio
import json
import logging
import os
import random
import re
import socket
import sqlite3
import sys
import time

import aiohttp

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.environ.get("BOT_DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
API_VERSION = "5.199"

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
log = logging.getLogger("vk_bot")

with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
    config = json.load(f)
TOKEN = (config.get("api_key") or config.get("token") or "").strip()

if not TOKEN:
    raise SystemExit("В config.json не указан api_key (ключ доступа сообщества VK)")

USER_DB_PATH = os.path.join(DATA_DIR, "user_data.db")
LAST_REPLY_KEYBOARD_FP = {}
CURRENT_MENU_FIELD = "current_menu_id"
USER_STATE = {}


def _reply_menu_signature(buttons):
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


def menu_layout_id(block_id: str, buttons) -> str:
    return f"{block_id}:{_reply_menu_signature(buttons)}"


def get_current_menu_id(user_id: int):
    try:
        val = get_user_field(user_id, CURRENT_MENU_FIELD)
    except Exception:
        val = None
    if val is None or str(val).strip() == "":
        return LAST_REPLY_KEYBOARD_FP.get(user_id)
    return str(val).strip()


def set_current_menu_id(user_id: int, menu_id: str | None):
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


# --- Сценарий ---

def load_scenario():
    path = os.path.join(BASE_DIR, "scenario.json")
    if not os.path.exists(path):
        return {"blocks": [], "connections": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


SCENARIO = load_scenario()
BLOCKS_BY_ID = {b["id"]: b for b in SCENARIO.get("blocks", [])}
NEXT_MAP = {}
for c in SCENARIO.get("connections", []):
    out = c.get("outputIndex", 0)
    if isinstance(out, str):
        out = int(out) if str(out).isdigit() else 0
    NEXT_MAP[(c["from"], out)] = c["to"]


# --- VK API ---

class VKClient:
    def __init__(self, token: str):
        self.token = token
        self.session: aiohttp.ClientSession | None = None
        self.group_id: int | None = None
        self.lp_server = None
        self.lp_key = None
        self.lp_ts = None
        self.lp_poll_url = None  # полный URL опроса (новый формат API)

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(family=socket.AF_INET),
            trust_env=True,
        )
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    async def call(self, method: str, **params):
        params["access_token"] = self.token
        params["v"] = API_VERSION
        url = f"https://api.vk.com/method/{method}"
        async with self.session.get(url, params=params) as resp:
            data = await resp.json(content_type=None)
        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"VK API {method}: [{err.get('error_code')}] {err.get('error_msg')}")
        return data.get("response")

    @staticmethod
    def _first_item(resp, nested_key: str = "groups"):
        """VK API: ответ может быть list или dict с вложенным списком."""
        if isinstance(resp, list):
            return resp[0] if resp else None
        if isinstance(resp, dict):
            if nested_key in resp and resp[nested_key]:
                item = resp[nested_key][0]
                return item
            if "items" in resp and resp["items"]:
                return resp["items"][0]
            if "id" in resp:
                return resp
        return None

    async def init_group(self):
        raw = await self.call("groups.getById")
        group = self._first_item(raw, "groups")
        if not group:
            raise RuntimeError(
                "Не удалось получить group_id. Проверьте токен сообщества (ключ доступа сообщества)."
            )
        self.group_id = group["id"] if isinstance(group, dict) else group.id
        log.info("VK group_id=%s", self.group_id)

    async def ensure_longpoll_settings(self):
        """Включаем нужные типы событий (сообщения, callback-кнопки)."""
        try:
            await self.call(
                "groups.setLongPollSettings",
                group_id=self.group_id,
                enabled=1,
                api_version=API_VERSION,
                message_new=1,
                message_reply=1,
                message_event=1,
            )
            log.info("Long Poll settings applied")
        except Exception as e:
            log.warning("setLongPollSettings: %s (проверьте Long Poll API в настройках группы)", e)

    async def init_longpoll(self):
        await self.ensure_longpoll_settings()
        lp = await self.call("groups.getLongPollServer", group_id=self.group_id)
        server = str(lp["server"]).strip()
        self.lp_key = str(lp["key"])
        self.lp_ts = str(lp["ts"])
        if server.startswith("http://") or server.startswith("https://"):
            self.lp_poll_url = server.rstrip("/")
            self.lp_server = None
        else:
            self.lp_server = server
            self.lp_poll_url = None
        log.info("Long Poll готов, endpoint=%s ts=%s", self.lp_poll_url or self.lp_server, self.lp_ts)

    def _longpoll_request_url(self) -> str:
        if self.lp_poll_url:
            return self.lp_poll_url
        return f"https://lp.vk.com/wh/{self.lp_server}"

    async def _fetch_longpoll(self) -> dict | None:
        url = self._longpoll_request_url()
        params = {
            "act": "a_check",
            "key": self.lp_key,
            "ts": str(self.lp_ts),
            "wait": "25",
        }
        async with self.session.get(
            url,
            params=params,
            timeout=aiohttp.ClientTimeout(total=40),
            headers={"User-Agent": "CreateBotsVK/1.0"},
        ) as resp:
            body = (await resp.text()).strip()
            if resp.status != 200:
                log.warning("Long Poll HTTP %s: %s", resp.status, body[:200])
                return None
            if not body:
                log.warning("Long Poll empty body")
                return None
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                log.warning("Long Poll invalid JSON: %r", body[:200])
                return None

    async def poll_events(self):
        data = await self._fetch_longpoll()
        if data is None:
            return []
        if "failed" in data:
            code = data["failed"]
            if code == 1:
                self.lp_ts = data.get("ts", self.lp_ts)
                return []
            if code == 2:
                await self.init_longpoll()
                return []
            if code == 3:
                await self.init_longpoll()
                return []
            log.warning("Long Poll failed=%s", code)
            return []
        self.lp_ts = data.get("ts", self.lp_ts)
        return data.get("updates", [])

    async def send_message(self, peer_id: int, text: str, keyboard=None):
        params = {
            "peer_id": peer_id,
            "message": text or " ",
            "random_id": random.randint(1, 2_147_000_000),
        }
        if keyboard:
            params["keyboard"] = keyboard if isinstance(keyboard, str) else json.dumps(keyboard, ensure_ascii=False)
        await self.call("messages.send", **params)

    async def send_media(self, peer_id: int, text: str, file_path: str, keyboard=None):
        upload_url_data = await self.call("photos.getMessagesUploadServer", peer_id=peer_id)
        upload_url = upload_url_data["upload_url"]
        form = aiohttp.FormData()
        form.add_field(
            "photo",
            open(file_path, "rb"),
            filename=os.path.basename(file_path),
            content_type="image/jpeg",
        )
        async with self.session.post(upload_url, data=form) as up_resp:
            upload_result = await up_resp.json(content_type=None)
        saved = await self.call(
            "photos.saveMessagesPhoto",
            server=upload_result["server"],
            photo=upload_result["photo"],
            hash=upload_result["hash"],
        )
        attachment = f"photo{saved[0]['owner_id']}_{saved[0]['id']}"
        params = {
            "peer_id": peer_id,
            "message": text or " ",
            "attachment": attachment,
            "random_id": random.randint(1, 2_147_000_000),
        }
        if keyboard:
            params["keyboard"] = keyboard if isinstance(keyboard, str) else json.dumps(keyboard, ensure_ascii=False)
        await self.call("messages.send", **params)

    async def answer_event(self, event_id: str, user_id: int, peer_id: int):
        try:
            await self.call(
                "messages.sendMessageEventAnswer",
                event_id=event_id,
                user_id=user_id,
                peer_id=peer_id,
            )
        except Exception as e:
            log.debug("event answer: %s", e)


vk: VKClient | None = None


# --- user_data.db (как в Telegram) ---

def _init_user_db():
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            user_id INTEGER NOT NULL,
            event_time REAL NOT NULL,
            event_type TEXT,
            block_id TEXT,
            direction TEXT DEFAULT 'inbound'
        )
    """)
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
    conn.close()


_init_user_db()


def _msk_now_str():
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")
    except Exception:
        from datetime import datetime
        return datetime.now().strftime("%d.%m.%Y %H:%M")


def is_new_user(user_id: int) -> bool:
    conn = sqlite3.connect(USER_DB_PATH)
    try:
        return conn.execute("SELECT 1 FROM users WHERE tg_user_id = ?", (user_id,)).fetchone() is None
    finally:
        conn.close()


def ensure_user_registered(user_id: int, username: str = None):
    now = time.time()
    name = username or str(user_id)
    conn = sqlite3.connect(USER_DB_PATH)
    try:
        if conn.execute("SELECT 1 FROM users WHERE tg_user_id = ?", (user_id,)).fetchone():
            return
        conn.execute(
            "INSERT INTO users (tg_user_id, tg_user_name, tg_user_date) VALUES (?, ?, ?)",
            (user_id, name, now),
        )
        for field, val in (
            ("tg_user_id", str(user_id)),
            ("tg_user_name", name),
            ("tg_user_date", _msk_now_str()),
        ):
            conn.execute(
                "INSERT OR REPLACE INTO user_data (user_id, field, value, updated_at) VALUES (?, ?, ?, ?)",
                (user_id, field, val, now),
            )
        conn.commit()
    finally:
        conn.close()


def get_user_field(user_id: int, field: str):
    conn = sqlite3.connect(USER_DB_PATH)
    r = conn.execute(
        "SELECT value FROM user_data WHERE user_id = ? AND field = ?",
        (user_id, field),
    ).fetchone()
    conn.close()
    return r[0] if r else None


def set_user_field(user_id: int, field: str, value):
    conn = sqlite3.connect(USER_DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO user_data (user_id, field, value, updated_at) VALUES (?, ?, ?, ?)",
        (user_id, field, str(value) if value is not None else "", time.time()),
    )
    conn.commit()
    conn.close()


def log_activity(user_id: int, event_type: str = "action", block_id: str = None, direction: str = "inbound"):
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
    if not block_id:
        return
    log_activity(user_id, event_type or "visit", block_id=str(block_id), direction="flow")


def log_user_command(user_id: int, command_text: str, block_id: str = None):
    cmd = (command_text or "").strip().lower().lstrip("/")
    if not cmd:
        return
    et = "start" if cmd == "start" else f"command:/{cmd}"
    log_activity(user_id, et, block_id=str(block_id) if block_id else None, direction="inbound")


def get_all_user_fields(user_id: int) -> dict:
    conn = sqlite3.connect(USER_DB_PATH)
    rows = conn.execute("SELECT field, value FROM user_data WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def strip_html(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"<br\\s*/?>", "\\n", text, flags=re.I)
    text = re.sub(r"</p>", "\\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    for a, b in (("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&")):
        text = text.replace(a, b)
    return text.strip()


def resolve_text(text: str, user_id: int) -> str:
    if not text:
        return text
    result = text
    for m in re.finditer(r"\\{\\{([a-zA-Z0-9_]+)\\}\\}", text):
        key = m.group(1)
        if key in ("current_timestamp", "now_msk", "now", "datetime"):
            val = _msk_now_str()
        elif key == "user_id":
            val = get_user_field(user_id, "tg_user_id")
        else:
            val = get_user_field(user_id, key)
        result = result.replace("{{" + key + "}}", str(val) if val is not None else "")
    return strip_html(result)


def get_start_next():
    for b in SCENARIO.get("blocks", []):
        if b.get("type") == "start":
            return NEXT_MAP.get((b["id"], 0))
    return None


def get_next_block(block_id, output_index=0):
    if isinstance(output_index, str):
        output_index = int(output_index) if str(output_index).isdigit() else 0
    return NEXT_MAP.get((block_id, output_index))


def _state(user_id: int) -> dict:
    return USER_STATE.setdefault(user_id, {})


def _clear_state(user_id: int):
    USER_STATE.pop(user_id, None)


def _build_reply_keyboard(buttons):
    if not buttons:
        return None
    if isinstance(buttons[0], str):
        buttons = [{"text": t} for t in buttons]
    rows = []
    for b in buttons:
        label = str((b.get("text") if isinstance(b, dict) else b) or "•")[:40]
        rows.append([{"action": {"type": "text", "label": label}, "color": "primary"}])
    return {"one_time": False, "inline": False, "buttons": rows}


def _build_inline_keyboard(inline_buttons, next_id):
    row_btns = []
    for btn in (inline_buttons or [])[:40]:
        label = str(btn.get("text") or "•")[:40]
        url = (btn.get("url") or "").strip()
        web = (btn.get("web_app") or "").strip() if isinstance(btn.get("web_app"), str) else ""
        link = url or web
        if link:
            row_btns.append({"type": "open_link", "label": label, "link": link})
        elif next_id:
            payload = json.dumps({"block_id": next_id}, ensure_ascii=False)
            row_btns.append({"type": "callback", "label": label, "payload": payload})
    if not row_btns and next_id:
        payload = json.dumps({"block_id": next_id}, ensure_ascii=False)
        row_btns.append({"type": "callback", "label": "Далее", "payload": payload})
    if not row_btns:
        return None
    rows = []
    row = []
    for i, b in enumerate(row_btns):
        if i > 0 and i % 2 == 0:
            rows.append(row)
            row = []
        if b["type"] == "open_link":
            row.append({"action": {"type": "open_link", "link": b["link"], "label": b["label"]}, "color": "primary"})
        else:
            row.append({"action": {"type": "callback", "label": b["label"], "payload": b["payload"]}, "color": "primary"})
    if row:
        rows.append(row)
    return {"one_time": False, "inline": True, "buttons": rows}


async def _send(peer_id: int, text: str, keyboard=None):
    await vk.send_message(peer_id, text, keyboard)


async def execute_block(peer_id: int, user_id: int, block_id: str, ctx=None):
    ctx = ctx or {}
    block = BLOCKS_BY_ID.get(block_id)
    if not block:
        return
    typ = block.get("type")
    data = block.get("data") or {}
    try:
        log_block_visit(user_id, block_id, "visit")
    except Exception:
        pass

    if typ == "data":
        action = data.get("action", "set")
        field = (data.get("fieldName") or "").strip()
        field_type = data.get("fieldType", "string")
        if not field:
            nxt = get_next_block(block_id, 0)
            if nxt:
                await execute_block(peer_id, user_id, nxt, ctx)
            return
        if action == "set" and data.get("valueSource") == "input":
            return ("await_input", {
                "block_id": block_id,
                "field": field,
                "field_type": field_type,
                "next_id": get_next_block(block_id, 0),
            })
        if action == "set":
            val = resolve_text(str(data.get("fieldValue") or ""), user_id)
            if field_type == "number":
                try:
                    val = str(float(val.replace(",", ".")))
                except ValueError:
                    val = "0"
            set_user_field(user_id, field, val)
        elif action == "add":
            cur = float(str(get_user_field(user_id, field) or "0").replace(",", "."))
            delta = float(str(resolve_text(str(data.get("fieldValue") or "0"), user_id)).replace(",", "."))
            set_user_field(user_id, field, str(cur + delta))
        elif action == "subtract":
            cur = float(str(get_user_field(user_id, field) or "0").replace(",", "."))
            delta = float(str(resolve_text(str(data.get("fieldValue") or "0"), user_id)).replace(",", "."))
            set_user_field(user_id, field, str(cur - delta))
        nxt = get_next_block(block_id, 0)
        if nxt:
            await execute_block(peer_id, user_id, nxt, ctx)
        return

    if typ == "condition":
        field = (data.get("fieldName") or "").strip()
        op = data.get("operator", "eq")
        compare_val = data.get("compareValue", "")
        actual = get_all_user_fields(user_id).get(field)
        ok = False
        if op == "exists":
            ok = bool(actual)
        elif op == "eq":
            ok = str(actual) == str(compare_val)
        elif op == "ne":
            ok = str(actual) != str(compare_val)
        else:
            try:
                a, c = float(actual or 0), float(compare_val or 0)
                ok = (op == "gt" and a > c) or (op == "lt" and a < c)
            except ValueError:
                ok = False
        nxt = get_next_block(block_id, 0 if ok else 1)
        if nxt:
            await execute_block(peer_id, user_id, nxt, ctx)
        return

    if typ == "message":
        text = resolve_text((data.get("text") or "").strip() or " ", user_id)
        media = data.get("media") or {}
        files = media.get("files") or []
        path = os.path.join(BASE_DIR, files[0].get("path", "")) if files else None
        kb = _build_inline_keyboard(data.get("inlineButtons") or [], get_next_block(block_id, 0))
        if media.get("type") == "photo" and path and os.path.exists(path):
            try:
                await vk.send_media(peer_id, text, path, kb)
            except Exception as e:
                log.warning("photo: %s", e)
                await _send(peer_id, text, kb)
        else:
            await _send(peer_id, text, kb)
        return

    if typ == "menu":
        buttons = data.get("buttons") or []
        target_id = menu_layout_id(str(block_id), buttons)
        current = get_current_menu_id(user_id)
        body = resolve_text((data.get("text") or data.get("name") or "Выберите действие"), user_id)
        # Always send the caption; attach keyboard only when layout changed.
        if current == target_id:
            await _send(peer_id, body or "Выберите действие:")
        else:
            await _send(peer_id, body or "Выберите действие:", _build_reply_keyboard(buttons))
            set_current_menu_id(user_id, target_id)
        return


async def run_from_block(peer_id: int, user_id: int, block_id: str, last_text: str = ""):
    block = BLOCKS_BY_ID.get(block_id)
    if not block:
        return
    typ = block.get("type")
    if typ == "menu":
        await execute_block(peer_id, user_id, block_id)
        st = _state(user_id)
        st["mode"] = "in_menu"
        st["block_id"] = block_id
        return
    if typ == "message":
        await execute_block(peer_id, user_id, block_id)
        nxt = get_next_block(block_id, 0)
        if nxt:
            await run_from_block(peer_id, user_id, nxt, last_text)
    elif typ in ("data", "condition"):
        result = await execute_block(peer_id, user_id, block_id)
        if result and result[0] == "await_input":
            _, info = result
            blk = BLOCKS_BY_ID.get(info["block_id"], {})
            prompt = resolve_text((blk.get("data") or {}).get("inputPrompt") or "Введите ответ:", user_id)
            st = _state(user_id)
            st.update(mode="awaiting_data_input", data_field=info["field"],
                      data_field_type=info.get("field_type", "string"), data_next_id=info.get("next_id"))
            await _send(peer_id, prompt, {"one_time": True, "inline": False, "buttons": []})


def get_all_menu_texts():
    texts = set()
    for b in SCENARIO.get("blocks", []):
        if b.get("type") != "menu":
            continue
        for btn in (b.get("data") or {}).get("buttons") or []:
            t = btn.get("text") if isinstance(btn, dict) else btn
            if t:
                texts.add(str(t).strip())
    texts.add("меню")
    texts.add("Меню")
    return texts


def menu_block_for_text(text: str):
    t = (text or "").strip()
    if t.lower() == "меню":
        for b in SCENARIO.get("blocks", []):
            if b.get("type") == "menu":
                return b["id"], 0
    for b in SCENARIO.get("blocks", []):
        if b.get("type") != "menu":
            continue
        btns = (b.get("data") or {}).get("buttons") or []
        if btns and isinstance(btns[0], str):
            btns = [{"text": x} for x in btns]
        for i, btn in enumerate(btns):
            label = (btn.get("text") if isinstance(btn, dict) else btn) or ""
            if label.strip() == t:
                return b["id"], i
    return None, None


COMMAND_TO_BLOCK = {}
COMMAND_ENTRY_BLOCK = {}
for cb in [b for b in SCENARIO.get("blocks", []) if b.get("type") == "command"]:
    cmd = (cb.get("data") or {}).get("command", "help").strip().lower().lstrip("/")
    COMMAND_TO_BLOCK[cmd] = get_next_block(cb["id"], 0)
    COMMAND_ENTRY_BLOCK[cmd] = cb.get("id")


def _start_block_id():
    for b in SCENARIO.get("blocks", []):
        if b.get("type") == "start":
            return b.get("id")
    return None


def _parse_payload(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


async def run_dialog(peer_id: int, user_id: int, text: str, payload: dict = None):
    """Главная логика: как у живых VK-ботов — любое сообщение ведёт по сценарию."""
    if payload:
        bid = payload.get("block_id")
        if bid and bid in BLOCKS_BY_ID:
            _clear_state(user_id)
            log_activity(user_id, "callback", block_id=str(bid), direction="inbound")
            await run_from_block(peer_id, user_id, bid)
            return

    text = (text or "").strip()
    st = _state(user_id)
    mode = st.get("mode")

    # Ключевые слова «с начала» (в VK нет обязательного /start)
    if text.lower() in ("начать", "старт", "start", "/start", "привет", "здравствуйте", "hello", "hi"):
        await handle_welcome(peer_id, user_id)
        return

    if mode == "awaiting_data_input":
        if text.lower() in get_all_menu_texts():
            _clear_state(user_id)
            await _send(peer_id, "Ввод отменён.")
            await show_main_menu(peer_id, user_id)
            return
        field = st.get("data_field", "")
        if st.get("data_field_type") == "number":
            try:
                val = str(float(text.replace(",", ".")))
            except ValueError:
                await _send(peer_id, "Введите число.")
                return
        else:
            val = text
        set_user_field(user_id, field, val)
        nxt = st.get("data_next_id")
        _clear_state(user_id)
        if nxt:
            await run_from_block(peer_id, user_id, nxt, text)
        else:
            await _send(peer_id, "Сохранено.")
        return

    if mode == "in_menu":
        block_id = st.get("block_id")
        block = BLOCKS_BY_ID.get(block_id)
        if block and block.get("type") == "menu":
            btns = (block.get("data") or {}).get("buttons") or []
            if btns and isinstance(btns[0], str):
                btns = [{"text": t} for t in btns]
            for i, btn in enumerate(btns):
                label = (btn.get("text") if isinstance(btn, dict) else btn) or ""
                if label.strip() == text:
                    log_activity(user_id, "menu", block_id=str(block_id) if block_id else None, direction="inbound")
                    _clear_state(user_id)
                    nxt = get_next_block(block_id, i)
                    if nxt:
                        await run_from_block(peer_id, user_id, nxt, text)
                    return
        await _send(peer_id, "Нажмите кнопку на клавиатуре или напишите «меню».")
        return

    cmd = text.lower().lstrip("/")
    if cmd in COMMAND_TO_BLOCK:
        _clear_state(user_id)
        log_user_command(user_id, cmd, block_id=COMMAND_ENTRY_BLOCK.get(cmd))
        nxt = COMMAND_TO_BLOCK[cmd]
        if nxt:
            await run_from_block(peer_id, user_id, nxt)
        return

    mid, idx = menu_block_for_text(text)
    if mid:
        _clear_state(user_id)
        nxt = get_next_block(mid, idx)
        if nxt:
            await run_from_block(peer_id, user_id, nxt, text)
        else:
            st["mode"] = "in_menu"
            st["block_id"] = mid
            await execute_block(peer_id, user_id, mid)
        return

    # Любое другое сообщение — приветствие / сценарий (типичное поведение VK)
    if is_new_user(user_id) or not st:
        await handle_welcome(peer_id, user_id)
        return

    if get_start_next():
        await handle_welcome(peer_id, user_id)
        return

    await show_main_menu(peer_id, user_id)


async def handle_welcome(peer_id: int, user_id: int):
    _clear_state(user_id)
    LAST_REPLY_KEYBOARD_FP.pop(peer_id, None)
    set_current_menu_id(user_id, None)
    log_user_command(user_id, "/start", block_id=_start_block_id())
    nxt = get_start_next()
    if nxt:
        await run_from_block(peer_id, user_id, nxt)
    else:
        await _send(peer_id, "Здравствуйте! Настройте сценарий: соедините блок «Старт» с сообщением.")


async def show_main_menu(peer_id: int, user_id: int):
    for b in SCENARIO.get("blocks", []):
        if b.get("type") == "menu":
            await execute_block(peer_id, user_id, b["id"])
            st = _state(user_id)
            st["mode"] = "in_menu"
            st["block_id"] = b["id"]
            return
    await _send(peer_id, "Напишите «меню» или «начать».")


async def process_update(update: dict):
    utype = update.get("type")
    obj = update.get("object") or {}

    if utype == "message_new":
        msg = obj.get("message") or obj
        if not msg or msg.get("out"):
            return
        peer_id = msg.get("peer_id")
        user_id = msg.get("from_id")
        if not peer_id or not user_id or user_id < 0:
            return
        text = msg.get("text") or ""
        payload = _parse_payload(msg.get("payload"))
        name = ""
        try:
            users_raw = await vk.call("users.get", user_ids=user_id)
            u = vk._first_item(users_raw, "profiles") or vk._first_item(users_raw, "users")
            if u:
                if isinstance(u, dict):
                    name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
                else:
                    name = f"{getattr(u, 'first_name', '')} {getattr(u, 'last_name', '')}".strip()
        except Exception:
            pass
        ensure_user_registered(user_id, name or str(user_id))
        log.info("msg peer=%s user=%s text=%r", peer_id, user_id, text[:80])
        await run_dialog(peer_id, user_id, text, payload)
        return

    if utype == "message_event":
        user_id = obj.get("user_id")
        peer_id = obj.get("peer_id")
        event_id = obj.get("event_id")
        if event_id and user_id and peer_id:
            await vk.answer_event(event_id, user_id, peer_id)
        payload = _parse_payload(obj.get("payload"))
        if user_id and peer_id:
            ensure_user_registered(user_id)
            await run_dialog(peer_id, user_id, "", payload)


async def main_loop():
    global vk
    log.info("VK bot starting...")
    async with VKClient(TOKEN) as client:
        vk = client
        await vk.init_group()
        await vk.init_longpoll()
        log.info("Слушаем Long Poll (сообщения сообщества)...")
        try:
            with open(os.path.join(BASE_DIR, "run.pid"), "w", encoding="utf-8") as pf:
                pf.write(str(os.getpid()))
        except OSError:
            pass
        while True:
            try:
                updates = await vk.poll_events()
                for upd in updates:
                    await process_update(upd)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("poll loop: %s", e)
                await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        log.info("stopped")
    except Exception as e:
        log.exception("fatal: %s", e)
        raise
'''
