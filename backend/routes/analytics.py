"""API аналитики ботов. Данные читаются из SQLite каждого бота (projects/bot_X/user_data.db)."""
import os
import sqlite3
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.db.database import get_db
from backend.models.bot import Bot
from backend.core.auth_deps import get_current_user_id_required
from backend.core.bot_access import is_desktop_app, require_bot_access
from backend.core import analytics as analytics_core
from backend.core.database import scenario_custom_field_names, scenario_field_types
from backend.core.analytics_import import ensure_bot_user_db
from backend.core.bot_data_store import ensure_extended_bot_tables, list_placeholder_suggestions

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
from backend.core.app_paths import PROJECTS_DIR


async def _check_bot_owner(db: AsyncSession, bot_id: int, user_id: int) -> bool:
    try:
        await require_bot_access(db, bot_id, user_id)
        return True
    except HTTPException:
        return False


@router.get("/bots")
async def list_my_bots(
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Список ботов пользователя для выбора в аналитике."""
    from sqlalchemy import select
    if is_desktop_app():
        result = await db.execute(select(Bot))
    else:
        result = await db.execute(select(Bot).where(Bot.user_id == user_id))
    bots = result.scalars().all()
    return [{"id": b.id, "name": b.name} for b in bots]


@router.get("/{bot_id}/overview")
async def get_analytics_overview(
    bot_id: int,
    period: str = Query("month", regex="^(day|week|month|custom|today|7d|30d)$"),
    range: str | None = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Сводка KPI (совместимость + новый формат)."""
    if not await _check_bot_owner(db, bot_id, user_id):
        raise HTTPException(status_code=403, detail="Нет доступа")
    range_key = range or {
        "day": "today",
        "week": "7d",
        "month": "30d",
        "today": "today",
        "7d": "7d",
        "30d": "30d",
        "custom": "custom",
    }.get(period, "30d")
    data = analytics_core.overview(
        bot_id, range_key=range_key, date_from=date_from, date_to=date_to
    )
    activity = analytics_core.activity_series(
        bot_id, range_key=range_key, date_from=date_from, date_to=date_to
    )
    return {
        **data,
        "users_total": data["total_subscribers"]["value"],
        "active_users": data["active_users"]["value"],
        "users_new": [
            {"date": p["date"], "count": p["new_users"]} for p in activity["series"]
        ],
        "activity": [
            {"date": p["date"], "count": p["messages_count"]} for p in activity["series"]
        ],
    }


@router.get("/{bot_id}/activity")
async def get_analytics_activity(
    bot_id: int,
    range: str = Query("30d"),
    date_from: str = Query(None),
    date_to: str = Query(None),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    if not await _check_bot_owner(db, bot_id, user_id):
        raise HTTPException(status_code=403, detail="Нет доступа")
    return analytics_core.activity_series(
        bot_id, range_key=range, date_from=date_from, date_to=date_to
    )


@router.get("/{bot_id}/funnel")
async def get_analytics_funnel(
    bot_id: int,
    range: str = Query("30d"),
    date_from: str = Query(None),
    date_to: str = Query(None),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    if not await _check_bot_owner(db, bot_id, user_id):
        raise HTTPException(status_code=403, detail="Нет доступа")
    return analytics_core.funnel(
        bot_id, range_key=range, date_from=date_from, date_to=date_to
    )


@router.get("/{bot_id}/activity-calendar")
async def get_activity_calendar(
    bot_id: int,
    year: int = Query(...),
    month: int = Query(...),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Календарь активности по дням за месяц."""
    if not await _check_bot_owner(db, bot_id, user_id):
        raise HTTPException(status_code=403, detail="Нет доступа")
    db_path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "user_data.db")
    if not os.path.exists(db_path):
        return {"days": {}}

    start = datetime(year, month, 1).timestamp()
    if month == 12:
        end = datetime(year + 1, 1, 1).timestamp() - 1
    else:
        end = datetime(year, month + 1, 1).timestamp() - 1

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """SELECT date(event_time, 'unixepoch', 'localtime') as d, COUNT(*) as cnt
               FROM activity_log WHERE event_time >= ? AND event_time <= ?
               GROUP BY d""",
            (start, end)
        )
        days = {r[0]: r[1] for r in cur.fetchall()}
    finally:
        conn.close()
    return {"days": days}


def _msk_example_date():
    """Пример даты в МСК для справки."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "18.02.2025 12:00"


@router.get("/{bot_id}/user-data-schema")
async def get_user_data_schema(
    bot_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Структура данных пользователей бота: поля и примеры. Для инструмента Справка."""
    if not await _check_bot_owner(db, bot_id, user_id):
        raise HTTPException(status_code=403, detail="Нет доступа")

    scenario_types = scenario_field_types(bot_id)
    scenario_fields = list(scenario_types.keys()) + scenario_custom_field_names(bot_id)
    field_set: set[str] = set()
    for name in scenario_fields:
        if name:
            field_set.add(name)

    db_path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "user_data.db")
    sample: dict[str, list] = {}
    field_types: dict[str, str] = dict(scenario_types)
    msk_date = _msk_example_date()

    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.execute("SELECT DISTINCT field FROM user_data ORDER BY field")
            for row in cur.fetchall():
                if row[0]:
                    fname = str(row[0])
                    if fname == "current_menu_id" or fname.startswith("_issued_"):
                        continue
                    field_set.add(fname)
        finally:
            conn.close()

    def _truncate_sample(val: str, limit: int = 48) -> str:
        text = str(val or "")
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "…"

    fields = sorted(field_set)
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        try:
            for f in fields[:50]:
                if f in field_types:
                    if f == "tg_user_id":
                        sample[f] = ["0000000001"]
                    elif f == "tg_user_name":
                        sample[f] = ["UserName"]
                    elif f == "tg_user_date":
                        sample[f] = [msk_date]
                    continue
                cur = conn.execute(
                    "SELECT DISTINCT value FROM user_data WHERE field = ? LIMIT 20",
                    (f,),
                )
                vals = [r[0] for r in cur.fetchall()]
                if vals:
                    first = next((v for v in vals if v is not None and str(v).strip()), None)
                    if first is not None:
                        try:
                            float(str(first).replace(",", "."))
                            sample[f] = ["100.0"]
                            field_types[f] = field_types.get(f, "number")
                        except (ValueError, TypeError):
                            sample[f] = [
                                _truncate_sample(v)
                                for v in dict.fromkeys(str(v) for v in vals if v is not None)
                            ][:5]
                            field_types[f] = field_types.get(f, "string")
                    else:
                        sample[f] = []
                        field_types.setdefault(f, "string")
                else:
                    sample[f] = []
                    field_types.setdefault(f, "string")
        finally:
            conn.close()

    for f in fields:
        field_types.setdefault(f, "string")
        sample.setdefault(f, [])

    placeholders: list[str] = []
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        try:
            ensure_extended_bot_tables(conn)
            placeholders = list_placeholder_suggestions(conn, bot_id)
        finally:
            conn.close()
    else:
        ensure_bot_user_db(bot_id)
        conn = sqlite3.connect(os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "user_data.db"))
        try:
            placeholders = list_placeholder_suggestions(conn, bot_id)
        finally:
            conn.close()

    return {
        "fields": fields,
        "sample": sample,
        "fieldTypes": field_types,
        "placeholders": placeholders,
    }
