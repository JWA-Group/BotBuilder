"""FastAPI routes for Broadcast Post Studio (bot audience posts)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import broadcast_studio as bs
from backend.core.auth_deps import get_current_user_id_required
from backend.core.bot_access import is_desktop_app, require_bot_access
from backend.core.broadcast import BroadcastError, fetch_broadcast_filters, normalize_telegram_html
from backend.db.database import get_db
from backend.models.bot import Bot

router = APIRouter(prefix="/api/broadcast", tags=["broadcast-studio"])


async def _ensure_access(db: AsyncSession, bot_id: int, user_id: int) -> None:
    await require_bot_access(db, bot_id, user_id)


class PostPayload(BaseModel):
    bot_id: int
    target_role: str = "all"
    audience_label: str = ""
    text_html: str = ""
    media_files: list[Any] = Field(default_factory=list)
    image_position: str = "before"
    inline_keyboard: list[Any] = Field(default_factory=list)
    tags: list[Any] = Field(default_factory=list)
    auto_delete_at: float | str | None = None
    scheduled_at: float | None = None
    post_id: int | None = None
    meta_only: bool = False


class NormalizePayload(BaseModel):
    html: str = ""


class AutoDeletePayload(BaseModel):
    bot_id: int
    auto_delete_at: float | str | None = None


@router.get("/bots")
async def list_broadcast_bots(
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
            if (getattr(b, "kind", None) or "scenario") != "moderator"
        ]
    }


@router.get("/{bot_id}/filters")
async def get_broadcast_filters(
    bot_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    try:
        return fetch_broadcast_filters(bot_id)
    except BroadcastError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    return {"posts": bs.list_posts(bot_id, limit=limit)}


@router.get("/posts/{post_id}")
async def get_post(
    post_id: int,
    bot_id: int = Query(...),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    post = bs.get_post(bot_id, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"post": post}


def _auto_delete_arg(body: PostPayload) -> float | None:
    try:
        return bs.parse_auto_delete_at(body.auto_delete_at)
    except (bs.BroadcastStudioError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/send-now")
async def send_now(
    body: PostPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, body.bot_id, user_id)
    try:
        post = bs.send_now(
            body.bot_id,
            target_role=body.target_role,
            audience_label=body.audience_label,
            text_html=body.text_html,
            media_files=body.media_files,
            image_position=body.image_position,
            inline_keyboard=body.inline_keyboard,
            tags=body.tags,
            auto_delete_at=_auto_delete_arg(body),
            post_id=body.post_id,
        )
        return {"ok": True, "post": post}
    except bs.BroadcastStudioError as exc:
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
        post = bs.schedule_post(
            body.bot_id,
            target_role=body.target_role,
            audience_label=body.audience_label,
            text_html=body.text_html,
            media_files=body.media_files,
            image_position=body.image_position,
            inline_keyboard=body.inline_keyboard,
            tags=body.tags,
            auto_delete_at=_auto_delete_arg(body),
            scheduled_at=float(body.scheduled_at),
            post_id=body.post_id,
        )
        return {"ok": True, "post": post}
    except bs.BroadcastStudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/draft")
async def save_draft(
    body: PostPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, body.bot_id, user_id)
    try:
        post = bs.save_draft(
            body.bot_id,
            target_role=body.target_role,
            audience_label=body.audience_label,
            text_html=body.text_html,
            media_files=body.media_files,
            image_position=body.image_position,
            inline_keyboard=body.inline_keyboard,
            tags=body.tags,
            auto_delete_at=_auto_delete_arg(body),
            post_id=body.post_id,
        )
        return {"ok": True, "post": post}
    except bs.BroadcastStudioError as exc:
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
        post = bs.edit_post(
            body.bot_id,
            post_id,
            target_role=body.target_role,
            audience_label=body.audience_label,
            text_html=body.text_html,
            media_files=body.media_files,
            image_position=body.image_position,
            inline_keyboard=body.inline_keyboard,
            tags=body.tags,
            auto_delete_at=body.auto_delete_at,
            scheduled_at=body.scheduled_at,
            meta_only=bool(body.meta_only),
        )
        return {"ok": True, "post": post}
    except bs.BroadcastStudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/posts/{post_id}/auto-delete")
async def patch_auto_delete(
    post_id: int,
    body: AutoDeletePayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, body.bot_id, user_id)
    try:
        post = bs.update_auto_delete(body.bot_id, post_id, body.auto_delete_at)
        return {"ok": True, "post": post}
    except bs.BroadcastStudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/posts/{post_id}")
async def remove_post(
    post_id: int,
    bot_id: int = Query(...),
    purge: bool = Query(False),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    try:
        if purge:
            result = bs.purge_post(bot_id, post_id)
        else:
            result = bs.delete_post(bot_id, post_id, deleted_by="manual")
        return result
    except bs.BroadcastStudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
