from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from ..models.command import Command
from ..schemas.command import CommandCreate

async def get_commands_by_bot(bot_id: int, db: AsyncSession):
    result = await db.execute(select(Command).where(Command.bot_id == bot_id))
    return result.scalars().all()

async def create_command(bot_id: int, cmd: CommandCreate, db: AsyncSession):
    new_cmd = Command(bot_id=bot_id, **cmd.dict())
    db.add(new_cmd)
    await db.commit()
    await db.refresh(new_cmd)
    return new_cmd
