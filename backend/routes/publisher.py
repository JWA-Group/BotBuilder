"""FastAPI routes for Telegram Post Publisher & Studio."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import publisher as pub
from backend.core.auth_deps import get_current_user_id_required
from backend.core.bot_access import is_desktop_app, require_bot_access
from backend.core.broadcast import normalize_telegram_html
from backend.core.channel_hub_store import connect_bot_db, list_channels
from backend.db.database import get_db
from backend.models.bot import Bot

router = APIRouter(prefix="/api/publisher", tags=["publisher"])


async def _ensure_access(db: AsyncSession, bot_id: int, user_id: int) -> None:
    await require_bot_access(db, bot_id, user_id)


class PostPayload(BaseModel):
    bot_id: int
    channel_id: str | int
    channel_title: str = ""
    text_html: str = ""
    media_files: list[Any] = Field(default_factory=list)
    inline_keyboard: list[Any] = Field(default_factory=list)
    scheduled_at: float | None = None
    post_id: int | None = None


class NormalizePayload(BaseModel):
    html: str = ""


@router.get("/bots")
async def list_publisher_bots(
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    if is_desktop_app():
        result = await db.execute(select(Bot))
    else:
        result = await db.execute(select(Bot).where(Bot.user_id == user_id))
    bots = result.scalars().all()
    return {
        "bots": [
            {
                "id": b.id,
                "name": b.name,
                "kind": getattr(b, "kind", None) or "scenario",
            }
            for b in bots
        ]
    }


@router.get("/{bot_id}/channels")
async def list_bot_channels(
    bot_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    conn = connect_bot_db(bot_id)
    try:
        channels = [
            ch
            for ch in list_channels(conn)
            if str(ch.get("chat_type") or "") == "channel"
        ]
        return {"channels": channels}
    finally:
        conn.close()


@router.post("/normalize")
async def normalize_html(body: NormalizePayload):
    return {"html": normalize_telegram_html(body.html or "")}


@router.get("/posts")
async def get_posts(
    bot_id: int = Query(...),
    limit: int = Query(100, ge=1, le=300),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    return {"posts": pub.list_posts(bot_id, limit=limit)}


@router.get("/posts/{post_id}")
async def get_post(
    post_id: int,
    bot_id: int = Query(...),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    post = pub.get_post(bot_id, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"post": post}


@router.post("/send-now")
async def send_now(
    body: PostPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, body.bot_id, user_id)
    try:
        post = pub.send_now(
            body.bot_id,
            channel_id=body.channel_id,
            channel_title=body.channel_title,
            text_html=body.text_html,
            media_files=body.media_files,
            inline_keyboard=body.inline_keyboard,
            post_id=body.post_id,
        )
        return {"ok": True, "post": post}
    except pub.PublisherError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/schedule")
async def schedule_post(
    body: PostPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, body.bot_id, user_id)
    if body.scheduled_at is None:
        raise HTTPException(status_code=400, detail="scheduled_at is required")
    try:
        post = pub.schedule_post(
            body.bot_id,
            channel_id=body.channel_id,
            channel_title=body.channel_title,
            text_html=body.text_html,
            media_files=body.media_files,
            inline_keyboard=body.inline_keyboard,
            scheduled_at=float(body.scheduled_at),
            post_id=body.post_id,
        )
        return {"ok": True, "post": post}
    except pub.PublisherError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/draft")
async def save_draft(
    body: PostPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, body.bot_id, user_id)
    try:
        post = pub.save_draft(
            body.bot_id,
            channel_id=body.channel_id,
            channel_title=body.channel_title,
            text_html=body.text_html,
            media_files=body.media_files,
            inline_keyboard=body.inline_keyboard,
            post_id=body.post_id,
        )
        return {"ok": True, "post": post}
    except pub.PublisherError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/posts/{post_id}")
async def update_post(
    post_id: int,
    body: PostPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, body.bot_id, user_id)
    try:
        post = pub.edit_post(
            body.bot_id,
            post_id,
            text_html=body.text_html,
            media_files=body.media_files,
            inline_keyboard=body.inline_keyboard,
            scheduled_at=body.scheduled_at,
            channel_id=str(body.channel_id) if body.channel_id is not None else None,
            channel_title=body.channel_title,
        )
        return {"ok": True, "post": post}
    except pub.PublisherError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/posts/{post_id}")
async def remove_post(
    post_id: int,
    bot_id: int = Query(...),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    try:
        result = pub.delete_post(bot_id, post_id)
        return result
    except pub.PublisherError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
