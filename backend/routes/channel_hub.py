"""FastAPI routes for Channel Analytics & Auto-Moderation Hub."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import channel_hub as hub
from backend.core.auth_deps import get_current_user_id_required
from backend.core.bot_access import require_bot_access
from backend.core.channel_hub_store import list_channels, connect_bot_db
from backend.db.database import get_db

router = APIRouter(prefix="/api/channel", tags=["channel-hub"])


async def _ensure_access(db: AsyncSession, bot_id: int, user_id: int) -> None:
    await require_bot_access(db, bot_id, user_id)


class RulesPayload(BaseModel):
    channel_id: int = 0
    forbidden_keywords: list[str] = Field(default_factory=list)
    allowed_urls_whitelist: list[str] = Field(default_factory=list)
    block_links: bool = True
    block_stickers: bool = False
    block_media: bool = False
    anti_flood: bool = False
    flood_max_messages: int = 5
    flood_time_window_seconds: int = 10
    flood_action: str = "warn"
    warn_decay_hours: int = 24
    instant_mute_on_warn: bool = False
    instant_mute_duration_minutes: int = 10
    max_warnings: int = 3
    mute_duration_minutes: int = 60
    mute_permanent: bool = False
    enabled: bool = True


class ModerationActionPayload(BaseModel):
    action: str
    chat_id: int
    user_id: int
    username: str = ""
    reason: str = ""
    duration_minutes: int | None = None
    message_id: int | None = None
    channel_id: int | None = None


class DeleteCommentPayload(BaseModel):
    bot_id: int
    chat_id: int
    message_id: int
    user_id: int = 0
    username: str = ""


@router.get("/bots")
async def list_channel_bots(
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Bots for Channel Hub — moderators first."""
    from sqlalchemy import select
    from backend.models.bot import Bot
    from backend.core.bot_access import is_desktop_app

    if is_desktop_app():
        result = await db.execute(select(Bot))
    else:
        result = await db.execute(select(Bot).where(Bot.user_id == user_id))
    bots = result.scalars().all()
    items = [
        {
            "id": b.id,
            "name": b.name,
            "kind": getattr(b, "kind", None) or "scenario",
        }
        for b in bots
    ]
    items.sort(key=lambda b: 0 if b["kind"] == "moderator" else 1)
    return {"bots": items}


class ModeratorSetupPayload(BaseModel):
    api_token: str
    name: str = ""


@router.post("/moderator/setup")
async def setup_moderator_bot(
    body: ModeratorSetupPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Create (or replace token of) the dedicated Channel Hub moderator bot and start it."""
    from sqlalchemy import select
    from backend.models.bot import Bot
    from backend.schemas.bot import BotCreate
    from backend.routes.bots import create_bot

    token = (body.api_token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Укажите API token из BotFather")

    result = await db.execute(select(Bot).where(Bot.kind == "moderator"))
    existing = result.scalars().first()
    if existing:
        existing.api_token = token
        if (body.name or "").strip():
            existing.name = body.name.strip()
        await db.commit()
        await db.refresh(existing)
        # Update config.json + regenerate + restart
        from backend.services.bot_service import create_bot_project
        from backend.routes.bot_runner import stop_bot, start_bot

        create_bot_project(
            existing.id,
            existing.name,
            token,
            platform="telegram",
            kind="moderator",
        )
        try:
            await stop_bot(existing.id)
        except Exception:
            pass
        started = await start_bot(existing.id)
        return {
            "id": existing.id,
            "name": existing.name,
            "kind": "moderator",
            "start": started,
            "updated": True,
        }

    created = await create_bot(
        BotCreate(
            name=(body.name or "").strip() or "Channel Moderator",
            api_token=token,
            user_id=user_id,
            platform="telegram",
            kind="moderator",
        ),
        db=db,
    )
    return created


@router.get("/{bot_id}/channels")
async def get_channels(
    bot_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    conn = connect_bot_db(bot_id)
    try:
        return {"channels": list_channels(conn)}
    finally:
        conn.close()


@router.get("/{bot_id}/overview")
async def get_overview(
    bot_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    return hub.overview(bot_id)


@router.get("/{bot_id}/growth")
async def get_growth(
    bot_id: int,
    days: int = 30,
    range: str | None = None,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    return hub.growth_series(bot_id, days=days, range_key=range)


@router.get("/{bot_id}/snapshot")
async def get_snapshot(
    bot_id: int,
    range: str = "30d",
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    # Local SQLite only — keep the event loop free for navigation / other windows.
    result = await asyncio.to_thread(hub.snapshot, bot_id, range_key=range)
    # Views scrape runs after the response is ready (no lock contention with snapshot).
    hub.schedule_public_post_views_refresh(bot_id)
    return result


@router.get("/{bot_id}/users/{target_user_id}")
async def get_user_inspector(
    bot_id: int,
    target_user_id: int,
    chat_id: int | None = None,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    return hub.user_inspector(bot_id, target_user_id, chat_id=chat_id)


@router.get("/{bot_id}/activity-hours")
async def get_activity_hours(
    bot_id: int,
    days: int = 14,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    return hub.activity_hours(bot_id, days=days)


@router.get("/{bot_id}/posts")
async def get_posts(
    bot_id: int,
    limit: int = 50,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    return hub.top_posts(bot_id, limit=limit)


@router.get("/{bot_id}/rules")
async def get_rules(
    bot_id: int,
    channel_id: int = 0,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    return hub.get_rules(bot_id, channel_id=channel_id)


@router.put("/{bot_id}/rules")
async def put_rules(
    bot_id: int,
    body: RulesPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    return hub.update_rules(bot_id, body.model_dump())


@router.get("/{bot_id}/comments")
async def get_comments(
    bot_id: int,
    limit: int = 100,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    return hub.list_comments(bot_id, limit=limit)


@router.get("/{bot_id}/restricted")
async def get_restricted(
    bot_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    return hub.list_restricted(bot_id)


@router.post("/{bot_id}/actions")
async def post_action(
    bot_id: int,
    body: ModerationActionPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    try:
        return hub.manual_action(
            bot_id,
            action=body.action,
            chat_id=body.chat_id,
            user_id=body.user_id,
            username=body.username,
            reason=body.reason,
            duration_minutes=body.duration_minutes,
            message_id=body.message_id,
            channel_id=body.channel_id,
        )
    except hub.ChannelHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{bot_id}/comments")
async def delete_channel_comment(
    bot_id: int,
    chat_id: int,
    message_id: int,
    target_user_id: int = 0,
    username: str = "",
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, bot_id, user_id)
    try:
        return hub.delete_comment(
            bot_id,
            chat_id=chat_id,
            message_id=message_id,
            user_id=target_user_id,
            username=username,
        )
    except hub.ChannelHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Spec alias: DELETE /api/telegram/comment
telegram_router = APIRouter(prefix="/api/telegram", tags=["telegram-moderation"])


@telegram_router.delete("/comment")
async def delete_telegram_comment(
    body: DeleteCommentPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, body.bot_id, user_id)
    try:
        return hub.delete_comment(
            body.bot_id,
            chat_id=body.chat_id,
            message_id=body.message_id,
            user_id=body.user_id,
            username=body.username,
        )
    except hub.ChannelHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
