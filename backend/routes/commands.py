from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from backend.db.database import get_db
from ..schemas.command import CommandCreate, CommandInDB
from ..services import command_service

router = APIRouter(tags=["Commands"])


@router.get("/{bot_id}", response_model=list[CommandInDB])
async def list_commands(bot_id: int, db: AsyncSession = Depends(get_db)):
    return await command_service.get_commands_by_bot(bot_id, db)

@router.post("/{bot_id}", response_model=CommandInDB)
async def add_command(bot_id: int, cmd: CommandCreate, db: AsyncSession = Depends(get_db)):
    return await command_service.create_command(bot_id, cmd, db)
