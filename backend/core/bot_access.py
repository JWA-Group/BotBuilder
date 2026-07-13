"""Проверка доступа к ботам в локальном desktop-режиме (без аккаунтов)."""

from __future__ import annotations

import os

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.models.bot import Bot


def is_desktop_app() -> bool:
    return os.environ.get("DESKTOP_APP") == "1"


async def require_bot_access(db: AsyncSession, bot_id: str | int, user_id: int) -> Bot:
    """
    Desktop: бот доступен, если существует в БД (один локальный пользователь).
    Web (legacy): только владелец user_id.
    """
    try:
        bid = int(bot_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Некорректный bot_id")

    if is_desktop_app():
        result = await db.execute(select(Bot).where(Bot.id == bid))
    else:
        result = await db.execute(select(Bot).where(Bot.id == bid, Bot.user_id == user_id))

    bot = result.scalar_one_or_none()
    if not bot:
        if is_desktop_app():
            raise HTTPException(status_code=404, detail="Бот не найден.")
        raise HTTPException(
            status_code=403,
            detail="Нет доступа к этому боту. Только владелец может выполнять это действие.",
        )
    return bot
