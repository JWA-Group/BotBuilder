"""Broadcast Post Studio — drafts, schedule, send, history for bot audiences."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from backend.core.app_paths import PROJECTS_DIR
from backend.core.broadcast import BroadcastError, normalize_telegram_html, resolve_media_path, start_broadcast
from backend.core.publisher import TAG_COLORS, PublisherError, _loads, _normalize_tags, parse_auto_delete_at

log = logging.getLogger("broadcast_studio")

BROADCAST_POSTS_DDL = """
CREATE TABLE IF NOT EXISTS broadcast_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL,
    target_role TEXT NOT NULL DEFAULT 'all',
    audience_label TEXT DEFAULT '',
    text_html TEXT NOT NULL DEFAULT '',
    media_files TEXT NOT NULL DEFAULT '[]',
    image_position TEXT NOT NULL DEFAULT 'before',
    inline_keyboard TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    auto_delete_at REAL NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    scheduled_at REAL NULL,
    job_id TEXT NULL,
    recipients_total INTEGER DEFAULT 0,
    recipients_sent INTEGER DEFAULT 0,
    recipients_failed INTEGER DEFAULT 0,
    error_message TEXT,
    deleted_at REAL NULL,
    deleted_by TEXT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
"""

BROADCAST_DELIVERIES_DDL = """
CREATE TABLE IF NOT EXISTS broadcast_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    telegram_message_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(post_id, chat_id, telegram_message_id)
)
"""

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class BroadcastStudioError(ValueError):
    """Invalid broadcast studio request."""


def _bot_db(bot_id: int) -> Path:
    return PROJECTS_DIR / f"bot_{bot_id}" / "user_data.db"


def connect_broadcast_db(bot_id: int) -> sqlite3.Connection:
    path = _bot_db(bot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(BROADCAST_POSTS_DDL)
    conn.execute(BROADCAST_DELIVERIES_DDL)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_broadcast_deliveries_post ON broadcast_deliveries(post_id)"
    )
    conn.commit()
    return conn


def save_deliveries(bot_id: int, post_id: int, deliveries: list[dict[str, Any]]) -> int:
    """Persist Telegram message ids so history delete can retract DMs."""
    if not deliveries:
        return 0
    now = time.time()
    conn = connect_broadcast_db(bot_id)
    saved = 0
    try:
        for item in deliveries:
            try:
                chat_id = int(item.get("chat_id"))
                mid = int(item.get("telegram_message_id") or item.get("message_id"))
            except (TypeError, ValueError):
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO broadcast_deliveries
                (post_id, chat_id, telegram_message_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (int(post_id), chat_id, mid, now),
            )
            saved += 1
        conn.commit()
    finally:
        conn.close()
    return saved


def list_deliveries(bot_id: int, post_id: int) -> list[dict[str, int]]:
    conn = connect_broadcast_db(bot_id)
    try:
        rows = conn.execute(
            """
            SELECT chat_id, telegram_message_id
            FROM broadcast_deliveries
            WHERE post_id = ?
            ORDER BY id ASC
            """,
            (int(post_id),),
        ).fetchall()
        return [
            {"chat_id": int(r["chat_id"]), "telegram_message_id": int(r["telegram_message_id"])}
            for r in rows
        ]
    finally:
        conn.close()


def _delete_telegram_deliveries(bot_id: int, post_id: int) -> tuple[int, list[str]]:
    """Best-effort deleteMessage for every stored delivery. Returns (ok_count, warnings)."""
    from backend.core.broadcast import (
        TelegramSendError,
        _load_bot_config,
        _tg_call_sync,
    )

    deliveries = list_deliveries(bot_id, post_id)
    if not deliveries:
        return 0, []

    try:
        config = _load_bot_config(bot_id)
        token = str(config.get("api_key") or "").strip()
    except Exception as exc:
        return 0, [str(exc)]
    if not token:
        return 0, ["Bot token missing"]

    ok = 0
    warnings: list[str] = []
    for item in deliveries:
        chat_id = int(item["chat_id"])
        mid = int(item["telegram_message_id"])
        try:
            _tg_call_sync(
                token,
                "deleteMessage",
                json_payload={"chat_id": chat_id, "message_id": mid},
            )
            ok += 1
        except TelegramSendError as exc:
            msg = str(exc)
            lower = msg.lower()
            # Already removed in the chat — count as retracted.
            if "message to delete not found" in lower:
                ok += 1
            else:
                warnings.append(f"{chat_id}/{mid}: {msg}")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{chat_id}/{mid}: {exc}")
    return ok, warnings


def _normalize_media_list(media_files: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in media_files or []:
        if isinstance(item, str):
            out.append({"path": item, "name": Path(item).name})
        elif isinstance(item, dict) and item.get("path"):
            out.append(
                {
                    "path": str(item["path"]),
                    "name": str(item.get("name") or Path(str(item["path"])).name),
                }
            )
    return out[:10]


def _split_media_paths(bot_id: int, media_files: list[Any]) -> tuple[list[str], list[str]]:
    image_paths: list[str] = []
    file_paths: list[str] = []
    for item in _normalize_media_list(media_files):
        rel = str(item["path"])
        try:
            full = resolve_media_path(bot_id, rel)
        except BroadcastError:
            continue
        if full.suffix.lower() in IMAGE_EXT:
            image_paths.append(rel)
        else:
            file_paths.append(rel)
    return image_paths, file_paths


def _row_to_post(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": int(row["id"]),
        "bot_id": int(row["bot_id"] or 0),
        "target_role": str(row["target_role"] or "all"),
        "audience_label": row["audience_label"] or "",
        "text_html": row["text_html"] or "",
        "media_files": _loads(row["media_files"], []),
        "image_position": str(row["image_position"] or "before"),
        "inline_keyboard": _loads(row["inline_keyboard"], []),
        "tags": _normalize_tags(_loads(row["tags"] if "tags" in keys else "[]", [])),
        "auto_delete_at": row["auto_delete_at"] if "auto_delete_at" in keys else None,
        "status": row["status"] or "draft",
        "scheduled_at": row["scheduled_at"],
        "job_id": row["job_id"] if "job_id" in keys else None,
        "recipients_total": int(row["recipients_total"] or 0) if "recipients_total" in keys else 0,
        "recipients_sent": int(row["recipients_sent"] or 0) if "recipients_sent" in keys else 0,
        "recipients_failed": int(row["recipients_failed"] or 0) if "recipients_failed" in keys else 0,
        "error_message": (row["error_message"] if "error_message" in keys else None) or "",
        "deleted_at": row["deleted_at"] if "deleted_at" in keys else None,
        "deleted_by": (row["deleted_by"] if "deleted_by" in keys else None) or None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_posts(bot_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 300))
    conn = connect_broadcast_db(bot_id)
    try:
        rows = conn.execute(
            """
            SELECT * FROM broadcast_posts
            ORDER BY COALESCE(deleted_at, scheduled_at, updated_at, created_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_post(r) for r in rows]
    finally:
        conn.close()


def get_post(bot_id: int, post_id: int) -> dict[str, Any] | None:
    conn = connect_broadcast_db(bot_id)
    try:
        row = conn.execute(
            "SELECT * FROM broadcast_posts WHERE id = ? LIMIT 1",
            (int(post_id),),
        ).fetchone()
        return _row_to_post(row) if row else None
    finally:
        conn.close()


def _save_post_row(
    bot_id: int,
    *,
    target_role: str = "all",
    audience_label: str = "",
    text_html: str = "",
    media_files: list[Any] | None = None,
    image_position: str = "before",
    inline_keyboard: list[Any] | None = None,
    tags: list[Any] | None = None,
    auto_delete_at: float | None = None,
    status: str = "draft",
    scheduled_at: float | None = None,
    job_id: str | None = None,
    recipients_total: int = 0,
    recipients_sent: int = 0,
    recipients_failed: int = 0,
    error_message: str = "",
    post_id: int | None = None,
) -> dict[str, Any]:
    now = time.time()
    media = _normalize_media_list(media_files or [])
    position = (image_position or "before").strip().lower()
    if position not in {"before", "after"}:
        position = "before"
    keyboard = inline_keyboard or []
    norm_tags = _normalize_tags(tags)
    tags_json = json.dumps(norm_tags, ensure_ascii=False)
    conn = connect_broadcast_db(bot_id)
    try:
        if post_id:
            existing = conn.execute(
                "SELECT status, deleted_at FROM broadcast_posts WHERE id = ?",
                (int(post_id),),
            ).fetchone()
            # Never resurrect a soft-deleted journal row via a later save/job update.
            if existing is not None:
                ex_status = str(existing["status"] or "")
                if ex_status == "deleted" or existing["deleted_at"]:
                    if status != "deleted":
                        row = conn.execute(
                            "SELECT * FROM broadcast_posts WHERE id = ?",
                            (int(post_id),),
                        ).fetchone()
                        return _row_to_post(row) if row else {"id": int(post_id), "status": "deleted"}
            conn.execute(
                """
                UPDATE broadcast_posts SET
                    target_role = ?, audience_label = ?, text_html = ?, media_files = ?,
                    image_position = ?, inline_keyboard = ?, tags = ?, auto_delete_at = ?,
                    status = ?, scheduled_at = ?, job_id = ?,
                    recipients_total = ?, recipients_sent = ?, recipients_failed = ?,
                    error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    str(target_role or "all"),
                    audience_label or "",
                    text_html or "",
                    json.dumps(media, ensure_ascii=False),
                    position,
                    json.dumps(keyboard, ensure_ascii=False),
                    tags_json,
                    auto_delete_at,
                    status,
                    scheduled_at,
                    job_id,
                    int(recipients_total),
                    int(recipients_sent),
                    int(recipients_failed),
                    error_message or "",
                    now,
                    int(post_id),
                ),
            )
            pid = int(post_id)
        else:
            cur = conn.execute(
                """
                INSERT INTO broadcast_posts
                (bot_id, target_role, audience_label, text_html, media_files, image_position,
                 inline_keyboard, tags, auto_delete_at, status, scheduled_at, job_id,
                 recipients_total, recipients_sent, recipients_failed, error_message,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(bot_id),
                    str(target_role or "all"),
                    audience_label or "",
                    text_html or "",
                    json.dumps(media, ensure_ascii=False),
                    position,
                    json.dumps(keyboard, ensure_ascii=False),
                    tags_json,
                    auto_delete_at,
                    status,
                    scheduled_at,
                    job_id,
                    int(recipients_total),
                    int(recipients_sent),
                    int(recipients_failed),
                    error_message or "",
                    now,
                    now,
                ),
            )
            pid = int(cur.lastrowid)
        conn.commit()
        row = conn.execute("SELECT * FROM broadcast_posts WHERE id = ?", (pid,)).fetchone()
        return _row_to_post(row)
    finally:
        conn.close()


def save_draft(
    bot_id: int,
    *,
    target_role: str = "all",
    audience_label: str = "",
    text_html: str = "",
    media_files: list[Any] | None = None,
    image_position: str = "before",
    inline_keyboard: list[Any] | None = None,
    tags: list[Any] | None = None,
    auto_delete_at: float | None = None,
    post_id: int | None = None,
) -> dict[str, Any]:
    return _save_post_row(
        bot_id,
        target_role=target_role,
        audience_label=audience_label,
        text_html=text_html,
        media_files=media_files,
        image_position=image_position,
        inline_keyboard=inline_keyboard,
        tags=tags,
        auto_delete_at=auto_delete_at,
        status="draft",
        post_id=post_id,
    )


def schedule_post(
    bot_id: int,
    *,
    target_role: str = "all",
    audience_label: str = "",
    text_html: str = "",
    media_files: list[Any] | None = None,
    image_position: str = "before",
    inline_keyboard: list[Any] | None = None,
    tags: list[Any] | None = None,
    auto_delete_at: float | None = None,
    scheduled_at: float,
    post_id: int | None = None,
) -> dict[str, Any]:
    if float(scheduled_at) <= time.time() - 5:
        raise BroadcastStudioError("scheduled_at must be in the future")
    return _save_post_row(
        bot_id,
        target_role=target_role,
        audience_label=audience_label,
        text_html=text_html,
        media_files=media_files,
        image_position=image_position,
        inline_keyboard=inline_keyboard,
        tags=tags,
        auto_delete_at=auto_delete_at,
        status="scheduled",
        scheduled_at=float(scheduled_at),
        post_id=post_id,
    )


def mark_job_finished(bot_id: int, post_id: int, job: dict[str, Any]) -> None:
    """Update broadcast_posts row when async delivery job completes."""
    post = get_post(bot_id, post_id)
    if not post:
        return

    deliveries = job.get("deliveries") or []
    if deliveries:
        save_deliveries(bot_id, int(post_id), list(deliveries))

    # Soft-delete wins over job completion — never resurrect a deleted journal row.
    if post.get("status") == "deleted" or post.get("deleted_at"):
        now = time.time()
        conn = connect_broadcast_db(bot_id)
        try:
            conn.execute(
                """
                UPDATE broadcast_posts
                SET recipients_total = ?,
                    recipients_sent = ?,
                    recipients_failed = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'deleted'
                """,
                (
                    int(job.get("total") or post.get("recipients_total") or 0),
                    int(job.get("sent") or 0),
                    int(job.get("failed") or 0),
                    now,
                    int(post_id),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        # Retract anything delivered after the user already hit Delete.
        try:
            _delete_telegram_deliveries(bot_id, int(post_id))
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Post-delete Telegram retract failed bot=%s post=%s: %s",
                bot_id,
                post_id,
                exc,
            )
        return

    job_status = str(job.get("status") or "")
    if job_status == "failed":
        final_status = "failed"
    elif job_status in ("completed", "cancelled"):
        # Partial send after cancel still counts as published when something went out.
        final_status = "published" if int(job.get("sent") or 0) > 0 or job_status == "completed" else "failed"
    else:
        final_status = "failed"

    error_message = str(job.get("error") or "")
    if job_status == "cancelled" and not error_message:
        error_message = "Delivery cancelled (post deleted)"
    if not error_message and job.get("errors"):
        errs = job.get("errors") or []
        if isinstance(errs, list) and errs:
            error_message = str(errs[0].get("error") if isinstance(errs[0], dict) else errs[0])

    _save_post_row(
        bot_id,
        target_role=post["target_role"],
        audience_label=post.get("audience_label") or "",
        text_html=post["text_html"],
        media_files=post["media_files"],
        image_position=post.get("image_position") or "before",
        inline_keyboard=post.get("inline_keyboard") or [],
        tags=post.get("tags") or [],
        auto_delete_at=post.get("auto_delete_at"),
        status=final_status,
        scheduled_at=post.get("scheduled_at"),
        job_id=post.get("job_id"),
        recipients_total=int(job.get("total") or post.get("recipients_total") or 0),
        recipients_sent=int(job.get("sent") or 0),
        recipients_failed=int(job.get("failed") or 0),
        error_message=error_message,
        post_id=post_id,
    )


def send_now(
    bot_id: int,
    *,
    target_role: str = "all",
    audience_label: str = "",
    text_html: str = "",
    media_files: list[Any] | None = None,
    image_position: str = "before",
    inline_keyboard: list[Any] | None = None,
    tags: list[Any] | None = None,
    auto_delete_at: float | None = None,
    post_id: int | None = None,
) -> dict[str, Any]:
    existing = get_post(bot_id, post_id) if post_id else None
    image_paths, file_paths = _split_media_paths(bot_id, media_files or (existing or {}).get("media_files") or [])

    prior_status = (existing or {}).get("status") or "draft"
    in_flight_status = prior_status if prior_status in ("scheduled", "draft", "failed") else "draft"

    saved = _save_post_row(
        bot_id,
        target_role=target_role,
        audience_label=audience_label,
        text_html=text_html,
        media_files=media_files,
        image_position=image_position,
        inline_keyboard=inline_keyboard,
        tags=tags,
        auto_delete_at=auto_delete_at,
        status=in_flight_status,
        scheduled_at=(existing or {}).get("scheduled_at"),
        post_id=post_id,
    )

    try:
        result = start_broadcast(
            bot_id,
            html_content=text_html,
            target_role=target_role,
            image_paths=image_paths,
            file_paths=file_paths,
            image_position=image_position,
            inline_keyboard=inline_keyboard,
            studio_post_id=saved["id"],
        )
    except BroadcastError as exc:
        _save_post_row(
            bot_id,
            target_role=target_role,
            audience_label=audience_label,
            text_html=text_html,
            media_files=media_files,
            image_position=image_position,
            inline_keyboard=inline_keyboard,
            tags=tags,
            auto_delete_at=auto_delete_at,
            status="failed",
            error_message=str(exc),
            post_id=saved["id"],
        )
        raise BroadcastStudioError(str(exc)) from exc

    return _save_post_row(
        bot_id,
        target_role=target_role,
        audience_label=audience_label,
        text_html=text_html,
        media_files=media_files,
        image_position=image_position,
        inline_keyboard=inline_keyboard,
        tags=tags,
        auto_delete_at=auto_delete_at,
        status="sending",
        scheduled_at=saved.get("scheduled_at"),
        job_id=str(result.get("job_id") or ""),
        recipients_total=int(result.get("recipients") or 0),
        post_id=saved["id"],
    )


def edit_post(
    bot_id: int,
    post_id: int,
    *,
    target_role: str | None = None,
    audience_label: str | None = None,
    text_html: str | None = None,
    media_files: list[Any] | None = None,
    image_position: str | None = None,
    inline_keyboard: list[Any] | None = None,
    tags: list[Any] | None = None,
    auto_delete_at: Any = ...,
    scheduled_at: float | None = None,
    meta_only: bool = False,
) -> dict[str, Any]:
    post = get_post(bot_id, post_id)
    if not post:
        raise BroadcastStudioError("Post not found")
    if post["status"] == "deleted":
        raise BroadcastStudioError("Deleted posts cannot be edited")

    new_role = target_role if target_role is not None else post["target_role"]
    new_label = audience_label if audience_label is not None else post.get("audience_label") or ""
    new_html = text_html if text_html is not None else post["text_html"]
    new_media = media_files if media_files is not None else post["media_files"]
    new_position = image_position if image_position is not None else post.get("image_position") or "before"
    new_keyboard = inline_keyboard if inline_keyboard is not None else post["inline_keyboard"]
    new_tags = _normalize_tags(tags if tags is not None else post.get("tags"))
    if auto_delete_at is ...:
        new_auto = post.get("auto_delete_at")
    else:
        try:
            new_auto = parse_auto_delete_at(auto_delete_at)
        except PublisherError as exc:
            raise BroadcastStudioError(str(exc)) from exc

    if meta_only:
        return _save_post_row(
            bot_id,
            target_role=new_role,
            audience_label=new_label,
            text_html=post["text_html"],
            media_files=post["media_files"],
            image_position=post.get("image_position") or "before",
            inline_keyboard=post["inline_keyboard"],
            tags=new_tags,
            auto_delete_at=new_auto,
            status=post["status"],
            scheduled_at=post.get("scheduled_at"),
            job_id=post.get("job_id"),
            recipients_total=post.get("recipients_total") or 0,
            recipients_sent=post.get("recipients_sent") or 0,
            recipients_failed=post.get("recipients_failed") or 0,
            error_message=post.get("error_message") or "",
            post_id=post_id,
        )

    if post["status"] in ("draft", "failed"):
        return _save_post_row(
            bot_id,
            target_role=new_role,
            audience_label=new_label,
            text_html=new_html,
            media_files=new_media,
            image_position=new_position,
            inline_keyboard=new_keyboard,
            tags=new_tags,
            auto_delete_at=new_auto,
            status="draft",
            post_id=post_id,
        )

    if post["status"] == "scheduled":
        sched = scheduled_at if scheduled_at is not None else post["scheduled_at"]
        return _save_post_row(
            bot_id,
            target_role=new_role,
            audience_label=new_label,
            text_html=new_html,
            media_files=new_media,
            image_position=new_position,
            inline_keyboard=new_keyboard,
            tags=new_tags,
            auto_delete_at=new_auto,
            status="scheduled",
            scheduled_at=sched,
            post_id=post_id,
        )

    if post["status"] == "published":
        return _save_post_row(
            bot_id,
            target_role=new_role,
            audience_label=new_label,
            text_html=post["text_html"],
            media_files=post["media_files"],
            image_position=post.get("image_position") or "before",
            inline_keyboard=post["inline_keyboard"],
            tags=new_tags,
            auto_delete_at=new_auto,
            status="published",
            job_id=post.get("job_id"),
            recipients_total=post.get("recipients_total") or 0,
            recipients_sent=post.get("recipients_sent") or 0,
            recipients_failed=post.get("recipients_failed") or 0,
            error_message=post.get("error_message") or "",
            post_id=post_id,
        )

    raise BroadcastStudioError(f"Cannot edit post with status={post['status']}")


def update_auto_delete(bot_id: int, post_id: int, auto_delete_at: Any) -> dict[str, Any]:
    return edit_post(bot_id, post_id, auto_delete_at=auto_delete_at, meta_only=True)


def _mark_soft_deleted(
    bot_id: int,
    post_id: int,
    *,
    deleted_by: str = "manual",
    error_message: str = "",
) -> dict[str, Any]:
    now = time.time()
    conn = connect_broadcast_db(bot_id)
    try:
        conn.execute(
            """
            UPDATE broadcast_posts
            SET status = 'deleted',
                deleted_at = ?,
                deleted_by = ?,
                auto_delete_at = NULL,
                error_message = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (now, deleted_by or "manual", error_message or "", now, int(post_id)),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM broadcast_posts WHERE id = ?", (int(post_id),)).fetchone()
        return _row_to_post(row) if row else {"id": post_id, "status": "deleted", "deleted_at": now}
    finally:
        conn.close()


def delete_post(bot_id: int, post_id: int, *, deleted_by: str = "manual") -> dict[str, Any]:
    """Soft-delete journal row and retract delivered Telegram DMs when ids are known."""
    from backend.core.broadcast import cancel_broadcast_job, pop_job_deliveries

    post = get_post(bot_id, post_id)
    if not post:
        raise BroadcastStudioError("Post not found")
    if post["status"] == "deleted":
        # Retry Telegram retract for already-deleted journal rows.
        from_telegram, warnings = _delete_telegram_deliveries(bot_id, post_id)
        return {
            "ok": True,
            "deleted": True,
            "id": post_id,
            "already": True,
            "from_telegram": from_telegram,
            "warnings": warnings[:10],
            "post": post,
        }

    job_id = post.get("job_id")
    # Stop further sends and capture in-memory message ids before they are lost.
    live_deliveries = cancel_broadcast_job(job_id) or pop_job_deliveries(job_id)
    if live_deliveries:
        save_deliveries(bot_id, int(post_id), live_deliveries)

    # Mark deleted locally first — Telegram failures must not block the journal.
    saved = _mark_soft_deleted(
        bot_id,
        post_id,
        deleted_by=deleted_by if deleted_by in ("manual", "auto") else "manual",
    )

    from_telegram = 0
    warnings: list[str] = []
    deliveries = list_deliveries(bot_id, post_id)
    if deliveries:
        from_telegram, warnings = _delete_telegram_deliveries(bot_id, post_id)
        if warnings and not from_telegram:
            saved = _mark_soft_deleted(
                bot_id,
                post_id,
                deleted_by=deleted_by if deleted_by in ("manual", "auto") else "manual",
                error_message="; ".join(warnings[:5]),
            )
        elif warnings:
            log.warning(
                "Partial Telegram retract bot=%s post=%s ok=%s warn=%s",
                bot_id,
                post_id,
                from_telegram,
                len(warnings),
            )
    elif post["status"] in ("published", "sending"):
        # Sent before delivery logging / job still flushing — journal delete still works.
        warnings.append(
            "No delivery log for this post yet; Telegram chats were not updated. "
            "If the send just finished, wait a second and delete again — or re-send after restart."
        )

    return {
        "ok": True,
        "deleted": True,
        "id": post_id,
        "from_telegram": from_telegram,
        "warnings": warnings[:10],
        "post": saved,
    }


def purge_post(bot_id: int, post_id: int) -> dict[str, Any]:
    post = get_post(bot_id, post_id)
    if not post:
        raise BroadcastStudioError("Post not found")
    # Best-effort retract before wiping the delivery log.
    if post.get("status") in ("published", "deleted"):
        try:
            _delete_telegram_deliveries(bot_id, post_id)
        except Exception as exc:
            log.warning("Purge Telegram retract skipped bot=%s post=%s: %s", bot_id, post_id, exc)
    conn = connect_broadcast_db(bot_id)
    try:
        conn.execute("DELETE FROM broadcast_deliveries WHERE post_id = ?", (int(post_id),))
        conn.execute("DELETE FROM broadcast_posts WHERE id = ?", (int(post_id),))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "purged": True, "id": post_id}


def _iter_bot_ids() -> list[int]:
    if not PROJECTS_DIR.is_dir():
        return []
    ids: list[int] = []
    for bot_dir in PROJECTS_DIR.glob("bot_*"):
        if not bot_dir.is_dir():
            continue
        try:
            bot_id = int(bot_dir.name.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        if (bot_dir / "user_data.db").is_file():
            ids.append(bot_id)
    return ids


def process_due_scheduled_broadcasts() -> int:
    """Send due scheduled broadcast posts. Returns count dispatched."""
    dispatched = 0
    now = time.time()
    for bot_id in _iter_bot_ids():
        try:
            conn = connect_broadcast_db(bot_id)
            rows = conn.execute(
                """
                SELECT id FROM broadcast_posts
                WHERE status = 'scheduled' AND scheduled_at IS NOT NULL AND scheduled_at <= ?
                  AND (job_id IS NULL OR job_id = '')
                ORDER BY scheduled_at ASC
                LIMIT 20
                """,
                (now,),
            ).fetchall()
            conn.close()
        except Exception:
            continue
        for row in rows:
            post = get_post(bot_id, int(row["id"]))
            if not post:
                continue
            try:
                send_now(
                    bot_id,
                    target_role=post.get("target_role") or "all",
                    audience_label=post.get("audience_label") or "",
                    text_html=post.get("text_html") or "",
                    media_files=post.get("media_files") or [],
                    image_position=post.get("image_position") or "before",
                    inline_keyboard=post.get("inline_keyboard") or [],
                    tags=post.get("tags") or [],
                    auto_delete_at=post.get("auto_delete_at"),
                    post_id=post["id"],
                )
                dispatched += 1
            except Exception as exc:
                log.warning("Scheduled broadcast failed bot=%s post=%s: %s", bot_id, post["id"], exc)
                try:
                    _save_post_row(
                        bot_id,
                        target_role=post.get("target_role") or "all",
                        audience_label=post.get("audience_label") or "",
                        text_html=post.get("text_html") or "",
                        media_files=post.get("media_files") or [],
                        image_position=post.get("image_position") or "before",
                        inline_keyboard=post.get("inline_keyboard") or [],
                        tags=post.get("tags") or [],
                        auto_delete_at=post.get("auto_delete_at"),
                        status="failed",
                        scheduled_at=post.get("scheduled_at"),
                        error_message=str(exc),
                        post_id=post["id"],
                    )
                except Exception:
                    pass
    return dispatched


def process_due_broadcast_auto_deletes() -> int:
    """Soft-delete published broadcast posts whose auto_delete_at has passed."""
    deleted = 0
    now = time.time()
    for bot_id in _iter_bot_ids():
        try:
            conn = connect_broadcast_db(bot_id)
            rows = conn.execute(
                """
                SELECT id FROM broadcast_posts
                WHERE status = 'published'
                  AND auto_delete_at IS NOT NULL
                  AND auto_delete_at <= ?
                ORDER BY auto_delete_at ASC
                LIMIT 20
                """,
                (now,),
            ).fetchall()
            conn.close()
        except Exception:
            continue
        for row in rows:
            try:
                delete_post(bot_id, int(row["id"]), deleted_by="auto")
                deleted += 1
            except Exception as exc:
                log.warning("Broadcast auto-delete failed bot=%s post=%s: %s", bot_id, row["id"], exc)
    return deleted


__all__ = [
    "TAG_COLORS",
    "BroadcastStudioError",
    "connect_broadcast_db",
    "list_posts",
    "get_post",
    "save_draft",
    "schedule_post",
    "send_now",
    "edit_post",
    "update_auto_delete",
    "delete_post",
    "purge_post",
    "save_deliveries",
    "list_deliveries",
    "mark_job_finished",
    "process_due_scheduled_broadcasts",
    "process_due_broadcast_auto_deletes",
    "parse_auto_delete_at",
    "normalize_telegram_html",
]
