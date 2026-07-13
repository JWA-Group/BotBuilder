"""Генерация scenario.json через Perplexity Sonar (один запрос: краткое ТЗ + сценарий)."""
from __future__ import annotations

import json
import logging
import os
import random
import re
import string
import urllib.error
import urllib.request
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

PERPLEXITY_URL = "https://api.perplexity.ai/v1/sonar"

VALID_TYPES = frozenset({"start", "message", "menu", "command", "data", "condition", "note"})

SYSTEM_PROMPT = """Ты проектируешь сценарии Telegram-бота для визуального редактора блоков.
Ответь ОДНИМ JSON-объектом без markdown и без текста вокруг. Только валидный JSON.

Формат ответа:
{
  "optimized_brief": "краткое техническое ТЗ на русском, 3–7 предложений: что делает бот и как устроен поток",
  "scenario": {
    "tags": [],
    "blocks": [ ... ],
    "connections": [ ... ]
  }
}

Правила scenario:
- Ровно один блок type \"start\" с id \"start\" (x≈80, y≈100).
- Остальные блоки: уникальные id из латинских букв, цифр, _, дефиса (например b_welcome_1).
- Каждый блок: {\"id\", \"type\", \"x\", \"y\", \"data\": { ... }}
- Типы: start, command, message, menu, data, condition (note не используй).
- **command** — отдельный блок для каждой текстовой команды Telegram вида /help, /order, /admin (поле data.command в нижнем регистре со слэшем). Если в запросе пользователя или во входном контексте перечислены команды — обязательно добавь для них блоки command и связи от них к нужным цепочкам; не заменяй команды одним блоком message без command.
- command.data: {\"command\": \"/help\"} — команда со слэшем в нижнем регистре.
- message.data: {\"text\": \"...\", \"media\": {\"type\": null, \"files\": []}, \"inlineButtons\": []}
  Подстановки из user_data ТОЛЬКО в виде {{имя_поля}} — одно имя: латинские буквы, цифры, подчёркивание (например {{total_orders}}, {{phone}}).
  Запрещено: {{поле || 0}}, {{поле ?? \"\"}}, любые выражения, функции или значения по умолчанию внутри фигурных скобок — движок их не поддерживает. Для «пусто если нет» используй отдельный блок condition или заведи поле в data заранее.
  Текст по желанию с такими плейсхолдерами.
- menu.data: {\"name\": \"подпись только в редакторе\", \"text\": \"текст пользователю (можно пусто)\", \"buttons\": [...] }
  В Telegram отправляется только \"text\"; \"name\" пользователю не показывается.
  Для телефона: {\"text\": \"Поделиться\", \"url\": \"\", \"request_contact\": true}
  Для геолокации: {\"text\": \"Где я\", \"url\": \"\", \"request_location\": true}
  (request_contact и request_location не на одной кнопке.)
- data.data: {\"action\": \"set\"|\"add\"|\"subtract\", \"fieldName\": \"...\", \"fieldValue\": \"...\",
    \"fieldType\": \"string\"|\"number\", \"valueSource\": \"const\"|\"input\",
    \"inputPrompt\": \"опционально — подсказка при input\"}
  valueSource \"input\" = отдельное текстовое сообщение пользователя (не подставляй {{...}} как ввод).
  Для копирования id/даты используй \"const\" и {{tg_user_id}}, {{tg_user_name}}, {{tg_user_date}}, {{user_id}} (=tg_user_id), {{now_msk}} или {{current_timestamp}}.
  Не выдумывай {{contact_phone}} — такого поля нет.
- Если во входном сообщении пользователя передан список **уже существующих имён полей** (user_data) — для того же смысла используй **точно эти** fieldName; не создавай синонимы (например не добавляй user_phone если уже есть phone). Новые fieldName добавляй только для действительно новых данных.
- condition.data: {\"fieldName\": \"...\", \"operator\": \"eq\"|\"ne\"|\"gt\"|\"lt\"|\"exists\"|\"role\", \"compareValue\": \"...\"}
  outputIndex 0 = условие истинно, 1 = ложно.

connections: [{\"from\": \"id\", \"to\": \"id\", \"outputIndex\": число}]
- Для start, command, data (после const/add/subtract), message (цепочка после сообщения): outputIndex 0.
- Для condition: 0 = ветка «да», 1 = «нет».
- Для menu с N кнопками: индексы 0..N-1 соответствуют кнопкам по порядку.
- Для message с M inline-кнопками: 0 = переход после текста без кнопки по цепочке; если кнопки есть, индексы 0..M-1 — связи с кнопок (как в меню).

Связь start → первый блок обязательна (outputIndex 0).
Располагай координаты x,y только приблизительно — сервер выровняет сетку по графу связей.
Делай 6–14 блоков, если пользователь не просит иначе.

fieldType \"number\" — только для сумм, количества, баланса, цены. Телефон, имя, email, адрес, ИНН, карта, геолокация как текст — всегда \"string\".
Телефон: \"const\"+{{...}} или input/контакт; геолокация: кнопка {\"request_location\": true} (без url), следующий блок data string сохранит \"широта,долгота\"."""


def _rand_suffix() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=6))


_STRING_FIELD_HINT = re.compile(
    r"(phone|tel|mobile|email|mail|name|имя|фио|address|адрес|inn|инн|passport|snils|card|карт|"
    r"телефон|location|geo|gps|lat|lng|coord|координ)",
    re.I,
)

# Подстановки только {{field}} — модель часто выдаёт {{field || 0}}; приводим к поддерживаемому виду.
_BAD_PLACEHOLDER_OR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\|\|[^}]+\}\}")
_NORM_PLACEHOLDER_SPACES = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def sanitize_user_placeholders(text: str) -> str:
    """Только {{имя_поля}} как в рантайме resolve_text; без ||, выражений и лишних пробелов."""
    if not isinstance(text, str) or not text:
        return text
    s = _BAD_PLACEHOLDER_OR.sub(lambda m: "{{" + m.group(1) + "}}", text)
    s = _NORM_PLACEHOLDER_SPACES.sub(lambda m: "{{" + m.group(1) + "}}", s)
    return s


def _field_name_implies_string(field_name: str) -> bool:
    return bool(field_name and _STRING_FIELD_HINT.search(field_name))


def layout_blocks_grid(blocks: list[dict[str, Any]], connections: list[dict[str, Any]]) -> None:
    """Выставляет x,y: BFS от start слева направо по слоям, остальные — правее."""
    if not blocks:
        return
    ids = {b["id"] for b in blocks}
    adj: dict[str, list[str]] = {bid: [] for bid in ids}
    for c in connections:
        fr = str(c.get("from") or "").strip()
        to = str(c.get("to") or "").strip()
        if fr in ids and to in ids and fr != to:
            adj[fr].append(to)
    depth: dict[str, int] = {bid: -1 for bid in ids}

    if "start" in ids:
        q: deque[str] = deque(["start"])
        depth["start"] = 0
        while q:
            u = q.popleft()
            for v in adj[u]:
                if depth[v] < 0:
                    depth[v] = depth[u] + 1
                    q.append(v)
    max_d = max((d for d in depth.values() if d >= 0), default=0)
    for bid in ids:
        if depth[bid] < 0:
            depth[bid] = max_d + 1
            max_d += 1
    by_layer: dict[int, list[str]] = {}
    for bid, d in depth.items():
        by_layer.setdefault(d, []).append(bid)
    col_w, row_h = 300, 170
    base_x, base_y = 80, 100
    for layer in sorted(by_layer.keys()):
        row_ids = sorted(by_layer[layer])
        for idx, bid in enumerate(row_ids):
            for b in blocks:
                if b.get("id") == bid:
                    b["x"] = base_x + layer * col_w
                    b["y"] = base_y + idx * row_h
                    break


def _extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Пустой ответ модели")
    fence = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("В ответе нет JSON-объекта")
        text = text[start : end + 1]
    return json.loads(text)


def _default_data(typ: str) -> dict[str, Any]:
    if typ == "message":
        return {"text": "Сообщение", "media": {"type": None, "files": []}, "inlineButtons": []}
    if typ == "menu":
        return {"name": "Меню", "text": "Выберите", "buttons": [{"text": "Далее", "url": ""}], "buttonRowBreaks": [0]}
    if typ == "command":
        return {"command": "/start", "tagId": ""}
    if typ == "data":
        return {"action": "set", "fieldType": "string", "fieldName": "field", "fieldValue": "", "valueSource": "const"}
    if typ == "condition":
        return {"fieldName": "role", "operator": "eq", "compareValue": "user"}
    if typ == "start":
        return {}
    return {}


def _normalize_block(b: dict[str, Any], idx: int) -> dict[str, Any] | None:
    if not isinstance(b, dict):
        return None
    typ = str(b.get("type") or "").strip().lower()
    if typ not in VALID_TYPES:
        return None
    bid = str(b.get("id") or "").strip()
    if typ == "start":
        bid = "start"
    elif not bid or not re.match(r"^[a-zA-Z0-9_-]+$", bid):
        bid = f"b_{typ}_{idx}_{_rand_suffix()}"
    try:
        x = int(b.get("x", 80 + idx * 220))
    except (TypeError, ValueError):
        x = 80 + idx * 220
    try:
        y = int(b.get("y", 100 + (idx % 3) * 120))
    except (TypeError, ValueError):
        y = 100
    data = b.get("data")
    if not isinstance(data, dict):
        data = {}
    defaults = _default_data(typ)
    merged = {**defaults, **data}
    if typ == "command":
        cmd = str(merged.get("command") or "/help").strip()
        if not cmd.startswith("/"):
            cmd = "/" + cmd
        merged["command"] = cmd.lower()
    if typ == "data":
        fv = merged.get("fieldValue")
        if merged.get("valueSource") == "input" and isinstance(fv, str) and "{{" in fv:
            merged["valueSource"] = "const"
        fn = str(merged.get("fieldName") or "")
        if str(merged.get("fieldType") or "").lower() == "number" and _field_name_implies_string(fn):
            merged["fieldType"] = "string"
        if isinstance(merged.get("inputPrompt"), str):
            merged["inputPrompt"] = sanitize_user_placeholders(merged["inputPrompt"])
        fv_s = merged.get("fieldValue")
        if isinstance(fv_s, str) and "{{" in fv_s:
            merged["fieldValue"] = sanitize_user_placeholders(fv_s)
    if typ == "message":
        if not isinstance(merged.get("media"), dict):
            merged["media"] = {"type": None, "files": []}
        m = merged["media"]
        if "type" not in m:
            m["type"] = None
        if "files" not in m or not isinstance(m["files"], list):
            m["files"] = []
        if not isinstance(merged.get("inlineButtons"), list):
            merged["inlineButtons"] = []
        inlines = merged.get("inlineButtons") or []
        if inlines and not isinstance(merged.get("inlineButtonRowBreaks"), list):
            merged["inlineButtonRowBreaks"] = list(range(len(inlines)))
        if isinstance(merged.get("text"), str):
            merged["text"] = sanitize_user_placeholders(merged["text"])
        for ib in merged.get("inlineButtons") or []:
            if isinstance(ib, dict) and isinstance(ib.get("text"), str):
                ib["text"] = sanitize_user_placeholders(ib["text"])
    if typ == "menu":
        btns = merged.get("buttons")
        if not isinstance(btns, list) or not btns:
            merged["buttons"] = [{"text": "OK", "url": ""}]
        else:
            fixed = []
            for item in btns:
                if isinstance(item, str):
                    fixed.append({"text": sanitize_user_placeholders(item)[:64], "url": ""})
                elif isinstance(item, dict):
                    row: dict[str, Any] = {
                        "text": sanitize_user_placeholders(str(item.get("text") or "Кнопка"))[:64],
                        "url": str(item.get("url") or ""),
                    }
                    if item.get("request_contact"):
                        row["request_contact"] = True
                    elif item.get("request_location"):
                        row["request_location"] = True
                    fixed.append(row)
                else:
                    fixed.append({"text": "Кнопка", "url": ""})
            merged["buttons"] = fixed
        if isinstance(merged.get("text"), str):
            merged["text"] = sanitize_user_placeholders(merged["text"])
        if isinstance(merged.get("name"), str):
            merged["name"] = sanitize_user_placeholders(merged["name"])
        n = len(merged["buttons"])
        merged["buttonRowBreaks"] = list(range(n)) if n else [0]
    return {"id": bid, "type": typ, "x": x, "y": y, "data": merged}


def normalize_scenario_payload(parsed: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Возвращает (optimized_brief, scenario_dict)."""
    brief = ""
    if isinstance(parsed.get("optimized_brief"), str):
        brief = parsed["optimized_brief"].strip()
    scenario = parsed.get("scenario")
    if not isinstance(scenario, dict):
        scenario = parsed if isinstance(parsed, dict) else {}

    raw_blocks = scenario.get("blocks")
    if not isinstance(raw_blocks, list):
        raw_blocks = []

    blocks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(raw_blocks):
        nb = _normalize_block(raw, i)
        if not nb:
            continue
        uid = nb["id"]
        if uid in seen_ids:
            nb["id"] = f"{uid}_{_rand_suffix()}"
            uid = nb["id"]
        seen_ids.add(uid)
        blocks.append(nb)

    deduped: list[dict[str, Any]] = []
    seen_start = False
    for b in blocks:
        if b.get("type") == "start":
            if seen_start:
                continue
            seen_start = True
            b["id"] = "start"
        deduped.append(b)
    blocks = deduped

    if not seen_start:
        blocks.insert(0, {"id": "start", "type": "start", "x": 80, "y": 100, "data": {}})

    ids_ok = {b["id"] for b in blocks}
    raw_conn = scenario.get("connections")
    if not isinstance(raw_conn, list):
        raw_conn = []
    connections: list[dict[str, Any]] = []
    for c in raw_conn:
        if not isinstance(c, dict):
            continue
        fr = str(c.get("from") or "").strip()
        to = str(c.get("to") or "").strip()
        if fr not in ids_ok or to not in ids_ok or fr == to:
            continue
        out = c.get("outputIndex", 0)
        try:
            out_i = int(out)
        except (TypeError, ValueError):
            out_i = 0
        connections.append({"from": fr, "to": to, "outputIndex": out_i})

    tags = scenario.get("tags")
    if not isinstance(tags, list):
        tags = []

    if "start" in ids_ok:
        has_from_start = any(x.get("from") == "start" for x in connections)
        non_start = [b for b in blocks if b.get("type") != "start"]
        if not has_from_start and non_start:
            connections.insert(0, {"from": "start", "to": non_start[0]["id"], "outputIndex": 0})

    if not brief:
        brief = "Сценарий сгенерирован по вашему описанию."

    layout_blocks_grid(blocks, connections)

    return brief, {"tags": tags, "blocks": blocks, "connections": connections}


def extract_field_and_command_hints(scenario: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Имена полей из блоков data и команды из command — для контекста ИИ."""
    fields: list[str] = []
    cmds: list[str] = []
    for b in scenario.get("blocks") or []:
        if not isinstance(b, dict):
            continue
        typ = str(b.get("type") or "")
        raw_data = b.get("data")
        data = raw_data if isinstance(raw_data, dict) else {}
        if typ == "data":
            fn = str(data.get("fieldName") or "").strip()
            if fn:
                fields.append(fn)
        elif typ == "command":
            c = str(data.get("command") or "").strip().lower()
            if c:
                cmds.append(c if c.startswith("/") else "/" + c)

    def _dedupe(xs: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return _dedupe(fields), _dedupe(cmds)


def _build_user_message(
    user_description: str,
    known_field_names: list[str] | None,
    existing_commands: list[str] | None,
) -> str:
    desc = user_description.strip()
    fields = [str(x).strip() for x in (known_field_names or []) if str(x).strip()]
    cmds = [str(x).strip().lower() for x in (existing_commands or []) if str(x).strip()]
    # уникальные, порядок стабильный
    seen: set[str] = set()
    fields_u: list[str] = []
    for f in fields:
        if f not in seen:
            seen.add(f)
            fields_u.append(f)
    seen_c: set[str] = set()
    cmds_u: list[str] = []
    for c in cmds:
        if c not in seen_c:
            seen_c.add(c)
            cmds_u.append(c if c.startswith("/") else "/" + c)

    parts = [f"Описание бота от автора:\n{desc}"]
    if fields_u or cmds_u:
        parts.append("")
        parts.append("Контекст текущего проекта (учти обязательно):")
        if cmds_u:
            parts.append(
                "Уже заданы блоки команд (command): "
                + ", ".join(cmds_u)
                + ". Сохрани эти команды и их смысл; дополни сценарий новыми блоками при необходимости, не выкидывай команды без причины."
            )
        if fields_u:
            parts.append(
                "Уже используются имена полей user_data (fieldName в блоках data и в {{...}} в текстах): "
                + ", ".join(fields_u)
                + ". Не дублируй те же данные под другими именами."
            )
    return "\n".join(parts)


def call_perplexity_scenario(
    user_description: str,
    *,
    known_field_names: list[str] | None = None,
    existing_commands: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
    if not key:
        raise ValueError("PERPLEXITY_API_KEY не задан в окружении")

    model = (os.environ.get("PERPLEXITY_MODEL") or "sonar").strip() or "sonar"
    user_content = _build_user_message(user_description, known_field_names, existing_commands)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.25,
        "max_tokens": 8000,
        "disable_search": True,
    }
    req = urllib.request.Request(
        PERPLEXITY_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        logger.warning("Perplexity HTTP %s: %s", e.code, err_body)
        raise ValueError(f"Ошибка API Perplexity ({e.code})") from e
    except urllib.error.URLError as e:
        logger.warning("Perplexity network: %s", e)
        raise ValueError("Не удалось связаться с Perplexity") from e

    try:
        content = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        logger.warning("Unexpected Perplexity response: %s", raw)
        raise ValueError("Неожиданный формат ответа Perplexity") from e

    if not isinstance(content, str):
        raise ValueError("Пустой контент ответа")

    parsed = _extract_json_object(content)
    if not isinstance(parsed, dict):
        raise ValueError("Корень JSON должен быть объектом")
    return normalize_scenario_payload(parsed)
