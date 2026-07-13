"""Broadcast manager: Telegram HTML sanitization, audience filters, async delivery."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import uuid
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

from backend.core.app_paths import PROJECTS_DIR
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"

TELEGRAM_ALLOWED_TAGS = frozenset({"b", "i", "u", "s", "a", "code", "pre"})
TAG_ALIASES = {
    "strong": "b",
    "em": "i",
    "strike": "s",
    "del": "s",
    "ins": "u",
}

SEND_DELAY_SEC = 0.04
CAPTION_LIMIT = 1024
TG_CONNECT_RETRIES = 3

_jobs: dict[str, dict[str, Any]] = {}


class BroadcastError(ValueError):
    """Invalid broadcast configuration or delivery failure."""


class TelegramSendError(RuntimeError):
    """Telegram Bot API returned an error."""


class TelegramForbiddenError(TelegramSendError):
    """User blocked the bot or chat is unavailable."""


HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
BLOCK_BREAK_TAGS = frozenset({"p", "div", "section", "article", "blockquote", "header", "footer", "li", "tr"})
TRANSPARENT_TAGS = frozenset(
    {
        "span",
        "font",
        "tbody",
        "thead",
        "tfoot",
        "ul",
        "ol",
        "table",
        "wrapper",
        "label",
        "small",
        "center",
    }
)


class TelegramHTMLNormalizer(HTMLParser):
    """Convert arbitrary rich HTML into Telegram Bot API HTML subset."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str] = []
        self.in_pre = False
        self._td_first = True

    def _newline(self) -> None:
        if not self.parts:
            return
        if not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def _close_tag(self, tag: str) -> None:
        if tag not in self.stack:
            return
        while self.stack:
            open_tag = self.stack.pop()
            self.parts.append(f"</{open_tag}>")
            if open_tag == tag:
                break

    def _close_all_inline(self) -> None:
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")

    def _href_from_attrs(self, attrs: list[tuple[str, str | None]]) -> str:
        for key, value in attrs:
            if key.lower() == "href" and value:
                return value.strip()
        return ""

    def _open_inline(self, tag: str, *, href: str | None = None) -> None:
        if tag in self.stack and tag in {"b", "i", "u", "s", "code"}:
            return
        self.stack.append(tag)
        if tag == "a" and href:
            self.parts.append(f'<a href="{escape(href, quote=True)}">')
        else:
            self.parts.append(f"<{tag}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.in_pre:
            if tag == "br":
                self.parts.append("\n")
            return

        if tag == "pre":
            self._close_all_inline()
            self._newline()
            self.in_pre = True
            self.stack.append("pre")
            self.parts.append("<pre>")
            return

        if tag == "code":
            self._open_inline("code")
            return

        if tag in HEADING_TAGS:
            self._close_all_inline()
            self._newline()
            self._open_inline("b")
            return

        if tag == "hr":
            self._close_all_inline()
            self._newline()
            self.parts.append("————————")
            self._newline()
            return

        if tag == "br":
            self.parts.append("\n")
            return

        if tag == "li":
            self._close_all_inline()
            self._newline()
            self.parts.append("• ")
            return

        if tag == "tr":
            self._close_all_inline()
            self._newline()
            self._td_first = True
            return

        if tag in {"td", "th"}:
            if not self._td_first:
                self.parts.append(" | ")
            self._td_first = False
            return

        if tag in BLOCK_BREAK_TAGS or tag in TRANSPARENT_TAGS:
            if tag in {"p", "div", "section", "article", "blockquote", "header", "footer"}:
                self._close_all_inline()
                self._newline()
            return

        normalized = TAG_ALIASES.get(tag, tag)
        if normalized == "a":
            href = self._href_from_attrs(attrs)
            if href.startswith(("http://", "https://", "tg://")):
                self._open_inline("a", href=href)
            return
        if normalized in TELEGRAM_ALLOWED_TAGS:
            self._open_inline(normalized)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.in_pre and tag == "pre":
            self.parts.append("</pre>")
            if self.stack and self.stack[-1] == "pre":
                self.stack.pop()
            self.in_pre = False
            self._newline()
            return
        if self.in_pre:
            return

        if tag in HEADING_TAGS:
            self._close_tag("b")
            self._newline()
            return

        if tag in {"p", "div", "section", "article", "blockquote", "header", "footer", "li", "tr"}:
            self._close_all_inline()
            self._newline()
            return

        if tag in {"td", "th", "ul", "ol", "table", "tbody", "thead", "tfoot"}:
            return

        if tag == "code":
            self._close_tag("code")
            return

        normalized = TAG_ALIASES.get(tag, tag)
        if normalized in TELEGRAM_ALLOWED_TAGS:
            self._close_tag(normalized)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(escape(data))

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def finish(self) -> None:
        self._close_all_inline()


def normalize_telegram_html(raw_html: str) -> str:
    """Convert rich editor HTML into Telegram-compliant markup."""
    text = (raw_html or "").strip()
    if not text:
        return ""

    parser = TelegramHTMLNormalizer()
    parser.feed(text)
    parser.close()
    parser.finish()

    result = "".join(parser.parts)
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\n[ \t]+", "\n", result)
    result = result.strip()

    result = re.sub(r"<([bius]|code)>\s*</\1>", "", result)
    result = re.sub(r"<pre>\s*</pre>", "", result)
    return result.strip()


def _bot_dir(bot_id: int) -> Path:
    return PROJECTS_DIR / f"bot_{bot_id}"


def _connect(bot_id: int) -> sqlite3.Connection:
    db_path = _bot_dir(bot_id) / "user_data.db"
    if not db_path.is_file():
        raise BroadcastError("База user_data.db не найдена. У бота пока нет подписчиков.")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _count_all_subscribers(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT tg_user_id AS uid FROM users
            UNION
            SELECT DISTINCT user_id AS uid FROM user_data WHERE user_id IS NOT NULL
        )
        """
    )
    return int(cur.fetchone()[0])


def _count_by_field_value(conn: sqlite3.Connection, field: str, value: str) -> int:
    cur = conn.execute(
        """
        SELECT COUNT(DISTINCT u.tg_user_id)
        FROM users u
        INNER JOIN user_data d ON d.user_id = u.tg_user_id
        WHERE d.field = ? AND d.value = ?
        """,
        (field, value),
    )
    row = cur.fetchone()
    return int(row[0] if row else 0)


def fetch_broadcast_filters(bot_id: int) -> dict[str, Any]:
    """Return audience filters: all subscribers, roles, and custom tag fields."""
    conn = _connect(bot_id)
    try:
        all_count = _count_all_subscribers(conn)
        filters: list[dict[str, Any]] = [
            {
                "id": "all",
                "label": "Все подписчики",
                "kind": "all",
                "count": all_count,
            }
        ]

        cur = conn.execute(
            """
            SELECT value, COUNT(DISTINCT user_id) AS cnt
            FROM user_data
            WHERE field = 'role' AND value IS NOT NULL AND TRIM(value) != ''
            GROUP BY value
            ORDER BY value
            """
        )
        for row in cur.fetchall():
            value = str(row["value"])
            filters.append(
                {
                    "id": f"role:{value}",
                    "label": f"Роль: {value}",
                    "kind": "role",
                    "value": value,
                    "count": int(row["cnt"]),
                }
            )

        cur = conn.execute(
            """
            SELECT field, value, COUNT(DISTINCT user_id) AS cnt
            FROM user_data
            WHERE field != 'role'
              AND value IS NOT NULL
              AND TRIM(value) != ''
              AND (
                    field = 'tag'
                 OR field LIKE '%_tag'
                 OR field LIKE 'tag_%'
              )
            GROUP BY field, value
            ORDER BY field, value
            LIMIT 100
            """
        )
        for row in cur.fetchall():
            field = str(row["field"])
            value = str(row["value"])
            filters.append(
                {
                    "id": f"field:{field}:{value}",
                    "label": f"{field} = {value}",
                    "kind": "tag",
                    "field": field,
                    "value": value,
                    "count": int(row["cnt"]),
                }
            )

        return {"filters": filters, "total_subscribers": all_count}
    finally:
        conn.close()


def resolve_recipient_ids(bot_id: int, target_role: str) -> list[int]:
    """Resolve Telegram user IDs for a filter id (all / role:x / field:y:z)."""
    target = (target_role or "all").strip()
    conn = _connect(bot_id)
    try:
        if target in ("", "all"):
            cur = conn.execute(
                """
                SELECT uid FROM (
                    SELECT tg_user_id AS uid FROM users
                    UNION
                    SELECT DISTINCT user_id AS uid FROM user_data WHERE user_id IS NOT NULL
                )
                ORDER BY uid
                """
            )
            return [int(row[0]) for row in cur.fetchall() if row[0] is not None]

        if target.startswith("role:"):
            role_value = target[5:]
            cur = conn.execute(
                """
                SELECT DISTINCT u.tg_user_id
                FROM users u
                INNER JOIN user_data d ON d.user_id = u.tg_user_id
                WHERE d.field = 'role' AND d.value = ?
                ORDER BY u.tg_user_id
                """,
                (role_value,),
            )
            return [int(row[0]) for row in cur.fetchall()]

        if target.startswith("field:"):
            parts = target.split(":", 2)
            if len(parts) != 3:
                raise BroadcastError(f"Некорректный фильтр: {target_role!r}")
            field_name, field_value = parts[1], parts[2]
            cur = conn.execute(
                """
                SELECT DISTINCT u.tg_user_id
                FROM users u
                INNER JOIN user_data d ON d.user_id = u.tg_user_id
                WHERE d.field = ? AND d.value = ?
                ORDER BY u.tg_user_id
                """,
                (field_name, field_value),
            )
            return [int(row[0]) for row in cur.fetchall()]

        # Legacy: plain role name without prefix.
        cur = conn.execute(
            """
            SELECT DISTINCT u.tg_user_id
            FROM users u
            INNER JOIN user_data d ON d.user_id = u.tg_user_id
            WHERE d.field = 'role' AND d.value = ?
            ORDER BY u.tg_user_id
            """,
            (target,),
        )
        ids = [int(row[0]) for row in cur.fetchall()]
        if ids:
            return ids
        raise BroadcastError(f"Неизвестный фильтр аудитории: {target_role!r}")
    finally:
        conn.close()


def _load_bot_config(bot_id: int) -> dict[str, Any]:
    config_path = _bot_dir(bot_id) / "config.json"
    if not config_path.is_file():
        raise BroadcastError("config.json бота не найден")
    with open(config_path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise BroadcastError("Некорректный config.json")
    return data


def resolve_media_path(bot_id: int, rel_path: str) -> Path:
    rel = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise BroadcastError(f"Недопустимый путь к файлу: {rel_path!r}")
    bot_dir = _bot_dir(bot_id).resolve()
    full = (bot_dir / rel).resolve()
    if bot_dir not in full.parents and full != bot_dir:
        raise BroadcastError(f"Путь вне проекта бота: {rel_path!r}")
    if not full.is_file():
        raise BroadcastError(f"Файл не найден: {rel_path!r}")
    return full


def _is_image_path(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _parse_telegram_response(resp: requests.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError as exc:
        raise TelegramSendError(
            f"Telegram API: некорректный ответ ({resp.status_code}): {resp.text[:200]}"
        ) from exc
    if not isinstance(data, dict):
        raise TelegramSendError("Telegram API: пустой ответ")
    if not data.get("ok"):
        description = str(data.get("description") or "Unknown error")
        lower = description.lower()
        if "blocked" in lower or "forbidden" in lower or "deactivated" in lower:
            raise TelegramForbiddenError(description)
        if "parse entities" in lower or "can't parse" in lower:
            raise TelegramSendError(
                "Telegram не принял HTML-разметку сообщения. Упростите форматирование."
            )
        raise TelegramSendError(description)
    result = data.get("result")
    return result if isinstance(result, dict) else {}


def _tg_call_sync(
    token: str,
    method: str,
    *,
    json_payload: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = TELEGRAM_API_BASE.format(token=token, method=method)
    last_exc: Exception | None = None
    for attempt in range(TG_CONNECT_RETRIES):
        try:
            resp = requests.post(
                url,
                json=json_payload,
                data=data,
                files=files,
                timeout=60,
            )
            return _parse_telegram_response(resp)
        except TelegramSendError:
            raise
        except requests.RequestException as exc:
            last_exc = exc
            if attempt + 1 < TG_CONNECT_RETRIES:
                import time

                time.sleep(1.2 * (attempt + 1))
                continue
            raise TelegramSendError(
                f"Не удалось связаться с Telegram ({exc}). Проверьте интернет/VPN/прокси."
            ) from exc
    raise TelegramSendError(str(last_exc or "Unknown Telegram transport error"))


async def _tg_call(
    token: str,
    method: str,
    *,
    json_payload: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _tg_call_sync,
        token,
        method,
        json_payload=json_payload,
        data=data,
        files=files,
    )


async def _send_photos(
    token: str,
    chat_id: int,
    image_paths: list[Path],
    caption: str | None,
) -> None:
    cap = (caption[:CAPTION_LIMIT] if caption else None) or None
    for index, image_path in enumerate(image_paths):
        payload: dict[str, Any] = {"chat_id": str(chat_id)}
        if index == 0 and cap:
            payload["caption"] = cap
            payload["parse_mode"] = "HTML"
        with open(image_path, "rb") as fh:
            files = {"photo": (image_path.name, fh.read())}
            await _tg_call(token, "sendPhoto", data=payload, files=files)
        await asyncio.sleep(SEND_DELAY_SEC)


async def _send_to_user(
    token: str,
    chat_id: int,
    html_text: str,
    image_paths: list[Path],
    file_paths: list[Path],
    *,
    image_position: str = "before",
) -> None:
    position = (image_position or "before").strip().lower()
    if position not in {"before", "after"}:
        position = "before"

    has_text = bool(html_text and html_text.strip())
    has_images = bool(image_paths)

    if position == "before":
        if has_images:
            await _send_photos(token, chat_id, image_paths, html_text if has_text else None)
        elif has_text:
            await _tg_call(
                token,
                "sendMessage",
                json_payload={
                    "chat_id": chat_id,
                    "text": html_text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            await asyncio.sleep(SEND_DELAY_SEC)
    else:
        if has_text:
            await _tg_call(
                token,
                "sendMessage",
                json_payload={
                    "chat_id": chat_id,
                    "text": html_text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            await asyncio.sleep(SEND_DELAY_SEC)
        if has_images:
            await _send_photos(token, chat_id, image_paths, None)

    for doc_path in file_paths:
        with open(doc_path, "rb") as fh:
            files = {"document": (doc_path.name, fh.read())}
            await _tg_call(
                token,
                "sendDocument",
                data={"chat_id": str(chat_id)},
                files=files,
            )
        await asyncio.sleep(SEND_DELAY_SEC)


async def _run_broadcast_job(
    job_id: str,
    bot_id: int,
    recipient_ids: list[int],
    html_text: str,
    image_paths: list[Path],
    file_paths: list[Path],
    token: str,
    image_position: str,
) -> None:
    job = _jobs[job_id]
    job["status"] = "running"
    job["total"] = len(recipient_ids)

    try:
        for chat_id in recipient_ids:
            try:
                await _send_to_user(
                    token,
                    chat_id,
                    html_text,
                    image_paths,
                    file_paths,
                    image_position=image_position,
                )
                job["sent"] += 1
            except TelegramForbiddenError:
                job["failed"] += 1
                job["errors"].append({"user_id": chat_id, "error": "blocked"})
            except TelegramSendError as exc:
                job["failed"] += 1
                job["errors"].append({"user_id": chat_id, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001 — per-recipient isolation
                job["failed"] += 1
                job["errors"].append({"user_id": chat_id, "error": str(exc)})
        job["status"] = "completed"
    except Exception as exc:  # noqa: BLE001
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        job["finished"] = True


def get_broadcast_job(job_id: str) -> dict[str, Any] | None:
    job = _jobs.get(job_id)
    if not job:
        return None
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "total": job.get("total", 0),
        "sent": job.get("sent", 0),
        "failed": job.get("failed", 0),
        "finished": job.get("finished", False),
        "error": job.get("error"),
        "errors": (job.get("errors") or [])[:20],
    }


def start_broadcast(
    bot_id: int,
    *,
    html_content: str,
    target_role: str,
    image_paths: list[str] | None = None,
    file_paths: list[str] | None = None,
    image_position: str = "before",
) -> dict[str, Any]:
    """Validate payload, queue async broadcast, return job metadata."""
    config = _load_bot_config(bot_id)
    platform = str(config.get("platform") or "telegram").lower()
    if platform != "telegram":
        raise BroadcastError("Рассылки пока поддерживаются только для Telegram-ботов")

    token = str(config.get("api_key") or "").strip()
    if not token:
        raise BroadcastError("API-токен бота не задан в config.json")

    normalized_html = normalize_telegram_html(html_content)
    images = [resolve_media_path(bot_id, p) for p in (image_paths or [])]
    files = [resolve_media_path(bot_id, p) for p in (file_paths or [])]

    if not normalized_html and not images and not files:
        raise BroadcastError("Добавьте текст сообщения или вложения")

    recipient_ids = resolve_recipient_ids(bot_id, target_role)
    if not recipient_ids:
        raise BroadcastError("По выбранному фильтру не найдено получателей")

    job_id = uuid.uuid4().hex
    _jobs[job_id] = {
        "bot_id": bot_id,
        "status": "queued",
        "total": len(recipient_ids),
        "sent": 0,
        "failed": 0,
        "finished": False,
        "errors": [],
        "error": None,
    }

    position = (image_position or "before").strip().lower()
    if position not in {"before", "after"}:
        position = "before"

    asyncio.create_task(
        _run_broadcast_job(
            job_id,
            bot_id,
            recipient_ids,
            normalized_html,
            images,
            files,
            token,
            position,
        )
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "recipients": len(recipient_ids),
        "normalized_html": normalized_html,
    }
