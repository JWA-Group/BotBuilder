import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from contextlib import asynccontextmanager

from backend.core.app_paths import ensure_data_dirs, get_app_db_path


def _database_url() -> str:
    ensure_data_dirs()
    db_path = get_app_db_path()
    # Absolute path: sqlite+aiosqlite:///C:/... (three slashes + posix path)
    return f"sqlite+aiosqlite:///{db_path.resolve().as_posix()}"


DATABASE_URL = _database_url()

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=os.environ.get("DESKTOP_APP") != "1" and os.environ.get("SQL_ECHO") == "1",
)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()

def _sync_migrate_users(sync_conn):
    """Добавляем колонки email/google для существующих таблиц users."""
    cols_to_add = [
        ("email", "ALTER TABLE users ADD COLUMN email VARCHAR"),
        ("email_verified", "ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 0"),
        ("verification_token", "ALTER TABLE users ADD COLUMN verification_token VARCHAR"),
        ("google_id", "ALTER TABLE users ADD COLUMN google_id VARCHAR"),
    ]
    for col, alter_sql in cols_to_add:
        try:
            r = sync_conn.execute(text(
                "SELECT COUNT(*) FROM pragma_table_info('users') WHERE name=:name"
            ), {"name": col})
            if r.scalar() == 0:
                sync_conn.execute(text(alter_sql))
        except Exception:
            pass


def _sync_migrate_bots(sync_conn):
    """Добавляем platform для существующих таблиц bots."""
    try:
        r = sync_conn.execute(text(
            "SELECT COUNT(*) FROM pragma_table_info('bots') WHERE name='platform'"
        ))
        if r.scalar() == 0:
            sync_conn.execute(text(
                "ALTER TABLE bots ADD COLUMN platform VARCHAR NOT NULL DEFAULT 'telegram'"
            ))
    except Exception:
        pass


def _ensure_default_user(sync_conn):
    r = sync_conn.execute(text("SELECT id FROM users WHERE id = 1"))
    if r.fetchone() is None:
        sync_conn.execute(
            text(
                "INSERT INTO users (id, login, password_hash, email_verified, created_at) "
                "VALUES (1, 'local', 'local', 1, datetime('now'))"
            )
        )


def _ensure_bots_local_owner(sync_conn):
    """Desktop: все боты принадлежат локальному пользователю id=1."""
    if os.environ.get("DESKTOP_APP") != "1":
        return
    sync_conn.execute(text("UPDATE bots SET user_id = 1 WHERE user_id IS NULL OR user_id != 1"))


async def init_db():
    from backend.models import user, bot, command, template

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sync_migrate_users)
        await conn.run_sync(_sync_migrate_bots)
        await conn.run_sync(_ensure_default_user)
        await conn.run_sync(_ensure_bots_local_owner)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
