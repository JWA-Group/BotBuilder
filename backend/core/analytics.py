"""Product analytics aggregations over per-bot SQLite (user_data.db)."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.core.analytics_import import ensure_bot_user_db

from backend.core.app_paths import PROJECTS_DIR

RANGE_PRESETS = {
    "today": 1,
    "7d": 7,
    "30d": 30,
}

MESSAGE_EVENT_TYPES = (
    "message",
    "text",
    "callback",
    "menu",
    "menu_contact",
    "menu_location",
    "start",
    "command",
    "action",
)
# Bot-side auto-traversal of canvas nodes — never counted as inbound messages.
FLOW_EVENT_TYPES = ("visit",)
ERROR_EVENT_TYPES = ("error", "exception", "fail", "failed")


def _bot_dir(bot_id: int) -> Path:
    return PROJECTS_DIR / f"bot_{bot_id}"


def _connect(bot_id: int) -> sqlite3.Connection:
    path = ensure_bot_user_db(bot_id)
    _ensure_activity_schema(path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_activity_schema(db_path: Path) -> None:
    """Ensure activity_log has block_id + direction columns (backward compatible)."""
    conn = sqlite3.connect(str(db_path))
    try:
        cols = _table_columns(conn, "activity_log")
        if "block_id" not in cols:
            conn.execute("ALTER TABLE activity_log ADD COLUMN block_id TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_activity_block ON activity_log(block_id)"
            )
        cols = _table_columns(conn, "activity_log")
        if "direction" not in cols:
            conn.execute(
                "ALTER TABLE activity_log ADD COLUMN direction TEXT DEFAULT 'inbound'"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_activity_direction ON activity_log(direction)"
            )
            # Backfill: treat known user-origin events as inbound; visits as flow.
            conn.execute(
                """
                UPDATE activity_log
                SET direction = CASE
                    WHEN lower(COALESCE(event_type, '')) IN ('visit') THEN 'flow'
                    WHEN lower(COALESCE(event_type, '')) LIKE 'visit:%' THEN 'flow'
                    WHEN block_id IS NOT NULL
                         AND lower(COALESCE(event_type, '')) IN ('visit', 'action')
                         THEN 'flow'
                    ELSE 'inbound'
                END
                WHERE direction IS NULL OR TRIM(direction) = ''
                """
            )
        conn.commit()
    finally:
        conn.close()


def _has_direction_column(conn: sqlite3.Connection) -> bool:
    return "direction" in _table_columns(conn, "activity_log")


def _inbound_sql_predicate(conn: sqlite3.Connection) -> tuple[str, tuple]:
    """
    SQL fragment that selects only user-originated (inbound) events.
    Excludes bot flow visits that inflate message volume.
    """
    if _has_direction_column(conn):
        return (
            "lower(COALESCE(direction, 'inbound')) = 'inbound'",
            (),
        )
    placeholders = ",".join("?" * len(MESSAGE_EVENT_TYPES))
    return (
        f"""(
          lower(COALESCE(event_type, '')) IN ({placeholders})
          OR lower(COALESCE(event_type, '')) LIKE 'command:%'
        )""",
        tuple(MESSAGE_EVENT_TYPES),
    )


def resolve_range(
    range_key: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[float, float, float, float, str]:
    """
    Returns (cur_start, cur_end, prev_start, prev_end, label).
    Default: last 30 days inclusive of today.
    """
    now = datetime.now(timezone.utc)
    end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    key = (range_key or "30d").strip().lower()
    if key in ("day", "today", "1d"):
        key = "today"
        days = 1
        label = "today"
    elif key in ("week", "7d", "7"):
        key = "7d"
        days = 7
        label = "7d"
    elif key in ("month", "30d", "30"):
        key = "30d"
        days = 30
        label = "30d"
    elif key == "custom" and date_from:
        try:
            start_dt = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
            if date_to:
                end_dt = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)
                end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            else:
                end_dt = end
            span = max(1, int((end_dt - start_dt).total_seconds() // 86400) + 1)
            prev_end = start_dt - timedelta(seconds=1)
            prev_start = prev_end - timedelta(days=span - 1)
            prev_start = prev_start.replace(hour=0, minute=0, second=0, microsecond=0)
            return (
                start_dt.timestamp(),
                end_dt.timestamp(),
                prev_start.timestamp(),
                prev_end.timestamp(),
                "custom",
            )
        except Exception:
            days = 30
            label = "30d"
    else:
        days = 30
        label = "30d"

    start_dt = (end - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    prev_end = start_dt - timedelta(seconds=1)
    prev_start = (prev_end - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (
        start_dt.timestamp(),
        end.timestamp(),
        prev_start.timestamp(),
        prev_end.timestamp(),
        label,
    )


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        if current == 0:
            return 0.0
        return 100.0
    return round(((current - previous) / previous) * 100.0, 1)


def _metric(value: float | int, previous: float | int) -> dict[str, Any]:
    return {
        "value": value,
        "previous": previous,
        "change_pct": _pct_change(float(value), float(previous)),
    }


def _count_subscribers(conn: sqlite3.Connection) -> int:
    users_tbl = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    n_users = 0
    if users_tbl:
        n_users = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] or 0)
    n_data = int(
        conn.execute("SELECT COUNT(DISTINCT user_id) FROM user_data").fetchone()[0] or 0
    )
    n_act = int(
        conn.execute("SELECT COUNT(DISTINCT user_id) FROM activity_log").fetchone()[0] or 0
    )
    return max(n_users, n_data, n_act)


def _distinct_active(conn: sqlite3.Connection, start: float, end: float) -> int:
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT user_id) FROM activity_log
        WHERE event_time >= ? AND event_time <= ?
        """,
        (start, end),
    ).fetchone()
    return int(row[0] or 0)


def _count_messages(conn: sqlite3.Connection, start: float, end: float) -> int:
    """Count inbound user messages/events only (never bot flow visits)."""
    pred, pred_args = _inbound_sql_predicate(conn)
    row = conn.execute(
        f"""
        SELECT COUNT(*) FROM activity_log
        WHERE event_time >= ? AND event_time <= ?
          AND {pred}
        """,
        (start, end, *pred_args),
    ).fetchone()
    return int(row[0] or 0)


def _count_errors(conn: sqlite3.Connection, start: float, end: float) -> int:
    placeholders = ",".join("?" * len(ERROR_EVENT_TYPES))
    row = conn.execute(
        f"""
        SELECT COUNT(*) FROM activity_log
        WHERE event_time >= ? AND event_time <= ?
          AND (
            lower(COALESCE(event_type, '')) IN ({placeholders})
            OR lower(COALESCE(event_type, '')) LIKE '%error%'
            OR lower(COALESCE(event_type, '')) LIKE '%exception%'
          )
        """,
        (start, end, *ERROR_EVENT_TYPES),
    ).fetchone()
    return int(row[0] or 0)


def _error_rate(errors: int, messages: int) -> float:
    if messages <= 0:
        return 0.0
    return round((errors / messages) * 100.0, 2)


def _load_scenario_blocks(bot_id: int) -> list[dict[str, Any]]:
    path = _bot_dir(bot_id) / "scenario.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    blocks = data.get("blocks") or []
    connections = data.get("connections") or []
    # BFS order from start for funnel presentation
    by_id = {str(b.get("id")): b for b in blocks if b.get("id") is not None}
    start_id = None
    for b in blocks:
        if (b.get("type") or "").lower() == "start":
            start_id = str(b.get("id"))
            break
    if not start_id and blocks:
        start_id = str(blocks[0].get("id"))

    outgoing: dict[str, list[str]] = {}
    for c in connections:
        src = str(c.get("from") or c.get("source") or "")
        dst = str(c.get("to") or c.get("target") or "")
        if src and dst:
            outgoing.setdefault(src, []).append(dst)

    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    queue = [start_id] if start_id else []
    while queue:
        bid = queue.pop(0)
        if not bid or bid in seen or bid not in by_id:
            continue
        seen.add(bid)
        b = by_id[bid]
        ordered.append(
            {
                "block_id": bid,
                "type": b.get("type") or "unknown",
                "label": _block_label(b),
            }
        )
        for nxt in outgoing.get(bid, []):
            if nxt not in seen:
                queue.append(nxt)
    for bid, b in by_id.items():
        if bid not in seen:
            ordered.append(
                {
                    "block_id": bid,
                    "type": b.get("type") or "unknown",
                    "label": _block_label(b),
                }
            )
    return ordered


def _block_label(block: dict[str, Any]) -> str:
    """Exact clean title for a scenario block — no truncation or description parsing."""
    data = block.get("data") or {}
    typ = (block.get("type") or "block").lower()
    bid = str(block.get("id") or "")
    if typ == "command":
        cmd = (data.get("command") or "").strip()
        if cmd:
            if not cmd.startswith("/"):
                cmd = "/" + cmd
            return cmd
        return bid or "command"
    if typ == "start":
        return "/start"
    for key in ("title", "name", "label"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().replace("\n", " ")
    buttons = data.get("buttons") or []
    if buttons:
        first = buttons[0]
        title = (first.get("text") if isinstance(first, dict) else first) or ""
        if str(title).strip():
            return str(title).strip()
    return bid or typ


def _interactive_blocks(bot_id: int) -> list[dict[str, Any]]:
    """
    Interaction Share rows: menu/inline button titles + slash commands as-is.
    Commands keep exact `/help` names; buttons use exact titles with type "message".
    Excludes /start, container menus, and Telegram "Главное меню".
    """
    path = _bot_dir(bot_id) / "scenario.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    skip_names = {
        "главное меню",
        "главное меню:",
        "main menu",
        "menu",
        "меню",
    }

    out: list[dict[str, Any]] = []
    for b in data.get("blocks") or []:
        typ = (b.get("type") or "").lower()
        bid = b.get("id")
        if bid is None:
            continue
        bid = str(bid)
        data_b = b.get("data") or {}

        if typ == "command":
            cmd = (data_b.get("command") or "").strip()
            if not cmd:
                continue
            if not cmd.startswith("/"):
                cmd = "/" + cmd
            cmd_key = cmd.lower()
            # Telegram system entry — do not show in share
            if cmd_key in ("/start", "start"):
                continue
            out.append(
                {
                    "block_id": bid,
                    "key": f"cmd:{cmd_key}",
                    "type": "command",
                    "name": cmd,
                    "label": cmd,  # backward-compatible alias
                    "command": cmd_key,
                    "button_text": None,
                    "menu_id": None,
                    "button_index": None,
                }
            )
            continue

        if typ == "menu":
            buttons = data_b.get("buttons") or []
            if buttons and isinstance(buttons[0], str):
                buttons = [{"text": t} for t in buttons]
            for i, btn in enumerate(buttons):
                if not isinstance(btn, dict):
                    title = str(btn or "").strip()
                else:
                    title = (btn.get("text") or "").strip()
                if not title:
                    title = f"{bid}#{i}"
                if title.lower().rstrip(":") in skip_names:
                    continue
                out.append(
                    {
                        "block_id": f"{bid}#{i}",
                        "key": f"btn:{bid}:{i}",
                        "type": "message",
                        "name": title,
                        "label": title,  # backward-compatible alias
                        "command": None,
                        "button_text": title,
                        "menu_id": bid,
                        "button_index": i,
                    }
                )
            continue

        # start / message / other — never listed as interaction share rows
    return out


def _command_block_map(interactive: list[dict[str, Any]]) -> dict[str, str]:
    """Map /command → interactive key (cmd block_id)."""
    mapping: dict[str, str] = {}
    for meta in interactive:
        if meta.get("type") != "command":
            continue
        cmd = meta.get("command")
        if not cmd:
            continue
        c = str(cmd).lower()
        mapping[c] = meta["block_id"]
        mapping[c.lstrip("/")] = meta["block_id"]
    return mapping


def _button_lookup(interactive: list[dict[str, Any]]) -> dict[str, str]:
    """Map button text (lower) and menu_id#idx → step block_id."""
    by_text: dict[str, str] = {}
    for meta in interactive:
        if meta.get("type") != "message":
            continue
        text = (meta.get("button_text") or meta.get("name") or meta.get("label") or "").strip().lower()
        if text:
            # last wins if duplicate titles across menus
            by_text[text] = meta["block_id"]
        mid = meta.get("menu_id")
        idx = meta.get("button_index")
        if mid is not None and idx is not None:
            by_text[f"{mid}#{idx}"] = meta["block_id"]
            by_text[f"btn:{mid}:{idx}"] = meta["block_id"]
    return by_text



def overview(bot_id: int, *, range_key: str = "30d", date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
    cur_start, cur_end, prev_start, prev_end, label = resolve_range(range_key, date_from, date_to)
    conn = _connect(bot_id)
    try:
        subscribers = _count_subscribers(conn)

        # DAU: average daily active users in current window
        dau_rows = conn.execute(
            """
            SELECT COUNT(DISTINCT user_id) AS c
            FROM activity_log
            WHERE event_time >= ? AND event_time <= ?
            GROUP BY date(event_time, 'unixepoch', 'localtime')
            """,
            (cur_start, cur_end),
        ).fetchall()
        dau = round(sum(int(r[0] or 0) for r in dau_rows) / max(len(dau_rows), 1), 1) if dau_rows else 0.0

        prev_dau_rows = conn.execute(
            """
            SELECT COUNT(DISTINCT user_id) AS c
            FROM activity_log
            WHERE event_time >= ? AND event_time <= ?
            GROUP BY date(event_time, 'unixepoch', 'localtime')
            """,
            (prev_start, prev_end),
        ).fetchall()
        prev_dau = (
            round(sum(int(r[0] or 0) for r in prev_dau_rows) / max(len(prev_dau_rows), 1), 1)
            if prev_dau_rows
            else 0.0
        )

        # MAU: distinct users in last 30 days (or current window if shorter)
        mau_start = min(cur_start, (datetime.now(timezone.utc) - timedelta(days=30)).timestamp())
        mau = _distinct_active(conn, mau_start, cur_end)
        prev_mau = _distinct_active(
            conn,
            mau_start - (cur_end - mau_start),
            mau_start - 1,
        )

        messages = _count_messages(conn, cur_start, cur_end)
        prev_messages = _count_messages(conn, prev_start, prev_end)
        errors = _count_errors(conn, cur_start, cur_end)
        prev_errors = _count_errors(conn, prev_start, prev_end)
        err_rate = _error_rate(errors, messages)
        prev_err_rate = _error_rate(prev_errors, prev_messages)

        # Subscribers growth in period (new registrations)
        new_subs = 0
        prev_new_subs = 0
        has_users = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        if has_users:
            new_subs = int(
                conn.execute(
                    "SELECT COUNT(*) FROM users WHERE tg_user_date >= ? AND tg_user_date <= ?",
                    (cur_start, cur_end),
                ).fetchone()[0]
                or 0
            )
            prev_new_subs = int(
                conn.execute(
                    "SELECT COUNT(*) FROM users WHERE tg_user_date >= ? AND tg_user_date <= ?",
                    (prev_start, prev_end),
                ).fetchone()[0]
                or 0
            )
        else:
            # First-seen in activity_log within window (lifetime first event)
            new_subs = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM (
                      SELECT user_id, MIN(event_time) AS first_ts
                      FROM activity_log GROUP BY user_id
                    ) WHERE first_ts >= ? AND first_ts <= ?
                    """,
                    (cur_start, cur_end),
                ).fetchone()[0]
                or 0
            )
            prev_new_subs = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM (
                      SELECT user_id, MIN(event_time) AS first_ts
                      FROM activity_log GROUP BY user_id
                    ) WHERE first_ts >= ? AND first_ts <= ?
                    """,
                    (prev_start, prev_end),
                ).fetchone()[0]
                or 0
            )

        active_period = _distinct_active(conn, cur_start, cur_end)
        prev_active = _distinct_active(conn, prev_start, prev_end)

        return {
            "bot_id": bot_id,
            "range": label,
            "period": {
                "start": datetime.fromtimestamp(cur_start, tz=timezone.utc).date().isoformat(),
                "end": datetime.fromtimestamp(cur_end, tz=timezone.utc).date().isoformat(),
            },
            "total_subscribers": _metric(subscribers, max(0, subscribers - new_subs + prev_new_subs)),
            "active_users": _metric(active_period, prev_active),
            "dau": _metric(dau, prev_dau),
            "mau": _metric(mau, prev_mau),
            "messages_sent": _metric(messages, prev_messages),
            "error_rate": _metric(err_rate, prev_err_rate),
            "new_subscribers": _metric(new_subs, prev_new_subs),
            "errors": _metric(errors, prev_errors),
        }
    finally:
        conn.close()


def activity_series(
    bot_id: int,
    *,
    range_key: str = "30d",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    cur_start, cur_end, _, _, label = resolve_range(range_key, date_from, date_to)
    conn = _connect(bot_id)
    try:
        # "Today" collapses to a single day — break into 24 hourly buckets instead
        if label == "today":
            hours = [f"{h:02d}:00" for h in range(24)]
            msg_map: dict[str, int] = {}
            pred, pred_args = _inbound_sql_predicate(conn)
            for row in conn.execute(
                f"""
                SELECT strftime('%H:00', event_time, 'unixepoch', 'localtime') AS h, COUNT(*) AS c
                FROM activity_log
                WHERE event_time >= ? AND event_time <= ?
                  AND {pred}
                GROUP BY h
                """,
                (cur_start, cur_end, *pred_args),
            ):
                msg_map[str(row[0])] = int(row[1] or 0)

            new_map: dict[str, int] = {}
            has_users = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone()
            if has_users:
                for row in conn.execute(
                    """
                    SELECT strftime('%H:00', tg_user_date, 'unixepoch', 'localtime') AS h, COUNT(*) AS c
                    FROM users
                    WHERE tg_user_date >= ? AND tg_user_date <= ?
                    GROUP BY h
                    """,
                    (cur_start, cur_end),
                ):
                    new_map[str(row[0])] = int(row[1] or 0)
            else:
                for row in conn.execute(
                    """
                    SELECT strftime('%H:00', first_ts, 'unixepoch', 'localtime') AS h, COUNT(*) AS c
                    FROM (
                      SELECT user_id, MIN(event_time) AS first_ts
                      FROM activity_log GROUP BY user_id
                    )
                    WHERE first_ts >= ? AND first_ts <= ?
                    GROUP BY h
                    """,
                    (cur_start, cur_end),
                ):
                    new_map[str(row[0])] = int(row[1] or 0)

            series = [
                {
                    "date": h,
                    "hour": h,
                    "new_users": new_map.get(h, 0),
                    "messages_count": msg_map.get(h, 0),
                }
                for h in hours
            ]
            return {
                "bot_id": bot_id,
                "range": label,
                "granularity": "hour",
                "series": series,
            }

        # Fill every calendar day in range
        start_date = datetime.fromtimestamp(cur_start, tz=timezone.utc).date()
        end_date = datetime.fromtimestamp(cur_end, tz=timezone.utc).date()
        days: list[str] = []
        cursor = start_date
        while cursor <= end_date:
            days.append(cursor.isoformat())
            cursor += timedelta(days=1)

        msg_map = {}
        pred, pred_args = _inbound_sql_predicate(conn)
        for row in conn.execute(
            f"""
            SELECT date(event_time, 'unixepoch', 'localtime') AS d, COUNT(*) AS c
            FROM activity_log
            WHERE event_time >= ? AND event_time <= ?
              AND {pred}
            GROUP BY d
            """,
            (cur_start, cur_end, *pred_args),
        ):
            msg_map[str(row[0])] = int(row[1] or 0)

        new_map = {}
        has_users = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        if has_users:
            for row in conn.execute(
                """
                SELECT date(tg_user_date, 'unixepoch', 'localtime') AS d, COUNT(*) AS c
                FROM users
                WHERE tg_user_date >= ? AND tg_user_date <= ?
                GROUP BY d
                """,
                (cur_start, cur_end),
            ):
                new_map[str(row[0])] = int(row[1] or 0)
        else:
            for row in conn.execute(
                """
                SELECT date(first_ts, 'unixepoch', 'localtime') AS d, COUNT(*) AS c
                FROM (
                  SELECT user_id, MIN(event_time) AS first_ts
                  FROM activity_log GROUP BY user_id
                )
                WHERE first_ts >= ? AND first_ts <= ?
                GROUP BY d
                """,
                (cur_start, cur_end),
            ):
                new_map[str(row[0])] = int(row[1] or 0)

        series = [
            {
                "date": d,
                "new_users": new_map.get(d, 0),
                "messages_count": msg_map.get(d, 0),
            }
            for d in days
        ]
        return {
            "bot_id": bot_id,
            "range": label,
            "granularity": "day",
            "series": series,
        }
    finally:
        conn.close()


def funnel(
    bot_id: int,
    *,
    range_key: str = "30d",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """
    Block Interaction Share — exact button titles (type=message) + exact slash
    commands (type=command). No description extraction or truncation.
    Excludes /start and Telegram "Главное меню".
    """
    cur_start, cur_end, _, _, label = resolve_range(range_key, date_from, date_to)
    interactive = _interactive_blocks(bot_id)
    cmd_map = _command_block_map(interactive)
    btn_map = _button_lookup(interactive)
    menu_ids = {
        m["menu_id"]
        for m in interactive
        if m.get("type") == "message" and m.get("menu_id")
    }
    step_ids = {m["block_id"] for m in interactive}

    conn = _connect(bot_id)
    try:
        counts: dict[str, int] = {m["block_id"]: 0 for m in interactive}
        has_dir = _has_direction_column(conn)
        dir_clause = (
            "AND lower(COALESCE(direction, 'inbound')) = 'inbound'"
            if has_dir
            else (
                "AND lower(COALESCE(event_type, '')) NOT IN ('visit') "
                "AND lower(COALESCE(event_type, '')) NOT LIKE 'visit:%'"
            )
        )

        # Direct hits: block_id may be command id, menu id, or btn:menu:idx / menu#idx
        for row in conn.execute(
            f"""
            SELECT COALESCE(block_id, '') AS bid, lower(COALESCE(event_type, '')) AS et, COUNT(*) AS c
            FROM activity_log
            WHERE event_time >= ? AND event_time <= ?
              {dir_clause}
            GROUP BY bid, et
            """,
            (cur_start, cur_end),
        ):
            bid = str(row[0] or "").strip()
            et = str(row[1] or "")
            c = int(row[2] or 0)
            if c <= 0:
                continue

            # Explicit button key stored as block_id
            if bid in step_ids:
                # Skip start-like command ids if somehow present
                counts[bid] = counts.get(bid, 0) + c
                continue
            if bid.startswith("btn:") and bid in btn_map:
                counts[btn_map[bid]] = counts.get(btn_map[bid], 0) + c
                continue
            if "#" in bid and bid in btn_map:
                counts[btn_map[bid]] = counts.get(btn_map[bid], 0) + c
                continue

            # Command events
            if et in ("start", "/start", "command:/start", "command:start"):
                continue  # never show /start
            if et.startswith("command:"):
                cmd = et.split(":", 1)[1].strip().lower()
                if cmd and not cmd.startswith("/"):
                    cmd = "/" + cmd
                if cmd in ("/start", "start"):
                    continue
                target = cmd_map.get(cmd) or cmd_map.get(cmd.lstrip("/"))
                if target:
                    counts[target] = counts.get(target, 0) + c
                continue
            if et == "command" and bid in cmd_map.values():
                counts[bid] = counts.get(bid, 0) + c
                continue

            # Menu / callback attributed to a menu container → split across its buttons
            # Prefer button-specific event_type: button:<text>
            if et.startswith("button:"):
                text = et.split(":", 1)[1].strip().lower()
                if text in ("главное меню", "главное меню:", "main menu"):
                    continue
                target = btn_map.get(text)
                if target:
                    counts[target] = counts.get(target, 0) + c
                continue

            if et in ("menu", "menu_contact", "menu_location", "callback"):
                # If block_id is a menu container, distribute to its buttons
                menu_buttons = [
                    m
                    for m in interactive
                    if m.get("type") == "message" and m.get("menu_id") == bid
                ]
                if not menu_buttons and len(menu_ids) == 1:
                    only = next(iter(menu_ids))
                    menu_buttons = [
                        m
                        for m in interactive
                        if m.get("type") == "message" and m.get("menu_id") == only
                    ]
                if menu_buttons:
                    share, rem = divmod(c, len(menu_buttons))
                    for i, m in enumerate(menu_buttons):
                        counts[m["block_id"]] = counts.get(m["block_id"], 0) + share + (
                            1 if i < rem else 0
                        )
                continue

        steps = [
            {
                "block_id": m["block_id"],
                "name": m["name"],
                "label": m["name"],  # backward-compatible alias
                "type": m["type"],
                "count": int(counts.get(m["block_id"], 0) or 0),
            }
            for m in interactive
        ]

        total_clicks = sum(s["count"] for s in steps)
        ordered: list[dict[str, Any]] = []
        for s in steps:
            c = s["count"]
            pct = round((c / total_clicks) * 100.0, 1) if total_clicks else 0.0
            ordered.append({**s, "percentage": pct})

        ordered.sort(key=lambda x: (-x["count"], x["name"]))

        return {
            "bot_id": bot_id,
            "range": label,
            "mode": "interaction_share",
            "baseline": total_clicks,
            "total_clicks": total_clicks,
            "steps": ordered,
            "has_block_tracking": total_clicks > 0,
        }
    finally:
        conn.close()
