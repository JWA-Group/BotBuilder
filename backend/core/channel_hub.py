"""Channel Hub analytics aggregations and manual Telegram moderation actions."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from backend.core.app_paths import PROJECTS_DIR
from backend.core.channel_hub_store import (
    apply_warning_decay,
    connect_bot_db,
    get_moderation_rules,
    list_channels,
    save_moderation_rules,
)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# Bot API Message has no `views` field — refresh public channels via t.me embed.
_VIEWS_REFRESH_AT: dict[int, float] = {}
_VIEWS_REFRESH_TTL_SEC = 25.0
_VIEWS_REFRESH_LOCK = threading.Lock()
_VIEWS_REFRESH_INFLIGHT: set[int] = set()
_VIEWS_EMBED_RE = re.compile(
    r'class="tgme_widget_message_views"[^>]*>([^<]+)<'
)
_VIEWS_BLOCK_RE = re.compile(
    r'data-post="([^"/]+)/(\d+)"[^>]*>([\s\S]*?)(?=data-post="|\Z)'
)


class ChannelHubError(ValueError):
    """Invalid Channel Hub request."""


def _parse_compact_count(raw: str) -> int:
    s = (raw or "").strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    if not s:
        return 0
    s = s.replace(",", ".")
    mult = 1.0
    last = s[-1:].upper()
    if last == "K":
        mult = 1_000.0
        s = s[:-1]
    elif last == "M":
        mult = 1_000_000.0
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        digits = re.sub(r"[^\d]", "", raw or "")
        return int(digits) if digits else 0


def _username_from_post_url(url: str | None) -> str:
    if not url:
        return ""
    m = re.match(r"(?i)^https?://t\.me/([^/]+)/\d+", (url or "").strip())
    if not m:
        return ""
    name = m.group(1).strip().lstrip("@")
    if name.lower() in ("c", "s"):
        return ""
    return name


def _fetch_embed_views(username: str, message_id: int, timeout: float = 3.0) -> int | None:
    uname = (username or "").strip().lstrip("@")
    if not uname or not message_id:
        return None
    url = f"https://t.me/{uname}/{int(message_id)}?embed=1"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BotBuilderChannelHub/1.0)"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None
        html = resp.text or ""
        if "Post not found" in html or "tgme_widget_message_error" in html:
            return None
        m = _VIEWS_EMBED_RE.search(html)
        if not m:
            return None
        return _parse_compact_count(m.group(1))
    except Exception:
        return None


def _parse_tme_message_views(html: str, username: str | None = None) -> dict[int, int]:
    """Map message_id -> views from a t.me or t.me/s HTML page."""
    out: dict[int, int] = {}
    uname = (username or "").strip().lstrip("@").lower()
    for m in _VIEWS_BLOCK_RE.finditer(html or ""):
        try:
            owner = (m.group(1) or "").strip().lstrip("@").lower()
            if uname and owner and owner != uname:
                continue
            mid = int(m.group(2))
            block = m.group(3) or ""
            vm = _VIEWS_EMBED_RE.search(block)
            if not vm:
                continue
            out[mid] = _parse_compact_count(vm.group(1))
        except Exception:
            continue
    return out


def _fetch_spage_views(
    username: str,
    *,
    needed_ids: set[int] | None = None,
    timeout: float = 8.0,
    max_pages: int = 4,
) -> dict[int, int]:
    """Parse posts from public preview https://t.me/s/{username} (with pagination)."""
    uname = (username or "").strip().lstrip("@")
    out: dict[int, int] = {}
    if not uname:
        return out
    before: int | None = None
    needed = set(needed_ids or ())
    for _ in range(max(1, min(int(max_pages), 8))):
        url = f"https://t.me/s/{uname}" + (f"?before={before}" if before else "")
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; BotBuilderChannelHub/1.0)"},
                timeout=timeout,
            )
            if resp.status_code != 200:
                break
            page = _parse_tme_message_views(resp.text or "", uname)
        except Exception:
            break
        if not page:
            break
        out.update(page)
        if needed and needed.issubset(out.keys()):
            break
        nxt = min(page.keys())
        if before is not None and nxt >= before:
            break
        before = nxt
    return out


def refresh_public_post_views(bot_id: int, *, force: bool = False, limit: int = 50) -> int:
    """
    Telegram Bot API does not expose Message.views.
    For public channels, pull view counters from t.me embed /s preview.

    Network I/O must NOT hold the SQLite connection — that froze Channel Manager
    (snapshot waited on the DB lock for 5–10s while t.me scraped).
    """
    now = time.time()
    last = _VIEWS_REFRESH_AT.get(int(bot_id), 0.0)
    ttl_ok = force or (now - last) >= _VIEWS_REFRESH_TTL_SEC

    usernames: dict[int, str] = {}
    targets: list[dict[str, Any]] = []
    conn = connect_bot_db(bot_id)
    try:
        usernames = {
            int(r["chat_id"]): (r["username"] or "").strip().lstrip("@")
            for r in conn.execute(
                "SELECT chat_id, username FROM channel_registry WHERE chat_type = 'channel'"
            ).fetchall()
        }
        rows = conn.execute(
            """
            SELECT id, channel_id, telegram_message_id, views_count, post_url
            FROM channel_posts
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 100)),),
        ).fetchall()

        for r in rows:
            uname = usernames.get(int(r["channel_id"]), "") or _username_from_post_url(
                r["post_url"] if "post_url" in r.keys() else None
            )
            if not uname:
                continue
            if ttl_ok or int(r["views_count"] or 0) <= 0:
                targets.append(
                    {
                        "id": int(r["id"]),
                        "channel_id": int(r["channel_id"]),
                        "telegram_message_id": int(r["telegram_message_id"]),
                        "views_count": int(r["views_count"] or 0),
                        "username": uname,
                    }
                )
    finally:
        conn.close()

    if not targets:
        return 0
    if ttl_ok:
        _VIEWS_REFRESH_AT[int(bot_id)] = now

    by_user: dict[str, list[dict[str, Any]]] = {}
    for t in targets:
        by_user.setdefault(t["username"], []).append(t)

    updates: list[tuple[int, int]] = []
    embed_budget = 4
    for uname, posts in by_user.items():
        needed = {int(p["telegram_message_id"]) for p in posts}
        try:
            page_views = _fetch_spage_views(uname, needed_ids=needed)
        except Exception:
            page_views = {}
        for p in posts:
            mid = int(p["telegram_message_id"])
            current = int(p["views_count"] or 0)
            views = page_views.get(mid)
            if views is None and embed_budget > 0 and (current <= 0 or ttl_ok):
                try:
                    views = _fetch_embed_views(uname, mid, timeout=2.5)
                except Exception:
                    views = None
                embed_budget -= 1
            if views is None:
                continue
            if int(views) > current:
                updates.append((int(views), int(p["id"])))

    if not updates:
        return 0

    conn = connect_bot_db(bot_id)
    updated = 0
    try:
        for views, row_id in updates:
            conn.execute(
                "UPDATE channel_posts SET views_count = ? WHERE id = ?",
                (views, row_id),
            )
            updated += 1
        if updated:
            conn.commit()
    finally:
        conn.close()
    return updated


def schedule_public_post_views_refresh(bot_id: int, *, force: bool = False) -> None:
    """Refresh t.me view counters in a daemon thread — never block the API response."""
    bid = int(bot_id)
    now = time.time()
    with _VIEWS_REFRESH_LOCK:
        if bid in _VIEWS_REFRESH_INFLIGHT:
            return
        last = _VIEWS_REFRESH_AT.get(bid, 0.0)
        if not force and last and (now - last) < _VIEWS_REFRESH_TTL_SEC:
            return
        _VIEWS_REFRESH_INFLIGHT.add(bid)

    def _run() -> None:
        try:
            # Let the interactive snapshot finish unlocking the UI first.
            time.sleep(0.4)
            refresh_public_post_views(bid, force=force)
        except Exception:
            pass
        finally:
            with _VIEWS_REFRESH_LOCK:
                _VIEWS_REFRESH_INFLIGHT.discard(bid)

    threading.Thread(
        target=_run,
        daemon=True,
        name=f"ch-views-{bid}",
    ).start()


def _bot_dir(bot_id: int) -> Path:
    return PROJECTS_DIR / f"bot_{bot_id}"


def _load_token(bot_id: int) -> str:
    path = _bot_dir(bot_id) / "config.json"
    if not path.is_file():
        raise ChannelHubError("config.json бота не найден")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    token = str((data or {}).get("api_key") or "").strip()
    if not token:
        raise ChannelHubError("API-токен бота не задан в config.json")
    return token


def _tg(token: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = TELEGRAM_API.format(token=token, method=method)
    resp = requests.post(url, json=payload, timeout=30)
    try:
        data = resp.json()
    except ValueError as exc:
        raise ChannelHubError(f"Telegram API bad response: {resp.text[:200]}") from exc
    if not data.get("ok"):
        raise ChannelHubError(str(data.get("description") or "Telegram API error"))
    return data.get("result") or {}


def _day_start(ts: float | None = None) -> float:
    now = datetime.fromtimestamp(ts or time.time(), tz=timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return start.timestamp()


def overview(bot_id: int) -> dict[str, Any]:
    conn = connect_bot_db(bot_id)
    try:
        channels = list_channels(conn)
        members = 0
        for ch in channels:
            if str(ch.get("chat_type") or "") in ("channel",):
                members = max(members, int(ch.get("members_count") or 0))
        if not members and channels:
            members = max(int(ch.get("members_count") or 0) for ch in channels)

        day0 = _day_start()
        joins = conn.execute(
            "SELECT COUNT(*) FROM channel_member_events WHERE event_type = 'join' AND timestamp >= ?",
            (day0,),
        ).fetchone()[0]
        leaves = conn.execute(
            "SELECT COUNT(*) FROM channel_member_events WHERE event_type = 'leave' AND timestamp >= ?",
            (day0,),
        ).fetchone()[0]
        moderated = conn.execute(
            "SELECT COUNT(*) FROM moderation_actions WHERE action IN ('warn','mute','ban','delete')"
        ).fetchone()[0]

        # Keep post.comments_count in sync with real discussion comments.
        _sync_post_comment_counts(conn)

        posts = conn.execute(
            """SELECT COALESCE(SUM(p.views_count),0), COALESCE(SUM(p.comments_count),0),
                      COALESCE(SUM(p.reactions_count),0), COUNT(*)
               FROM channel_posts p
               WHERE p.channel_id IN (
                   SELECT chat_id FROM channel_registry
                   WHERE chat_type = 'channel'
                     AND (IFNULL(username, '') != '' OR members_count IS NOT NULL)
               )
            """
        ).fetchone()
        views = int(posts[0] or 0)
        comments = int(posts[1] or 0)
        reactions = int(posts[2] or 0)
        post_count = int(posts[3] or 0)
        # Fallback: count all non-deleted comments if posts table lags.
        comments_live = conn.execute(
            "SELECT COUNT(*) FROM channel_comments WHERE is_deleted = 0"
        ).fetchone()[0]
        comments = max(comments, int(comments_live or 0))

        # Same units as per-post engagement index: views + comments*5 + reactions*2
        engagement_score = views + comments * 5 + reactions * 2
        err = 0.0
        if members > 0 and post_count > 0:
            err = round((engagement_score / (members * post_count)) * 100, 2)
        elif post_count > 0:
            # No member count yet — show average engagement index instead of 0.
            err = round(engagement_score / post_count, 2)

        return {
            "subscribers": members,
            "joins_today": int(joins or 0),
            "leaves_today": int(leaves or 0),
            "engagement_rate": err,
            "engagement_score": engagement_score,
            "comments_moderated": int(moderated or 0),
            "channels": channels,
            "posts_total": post_count,
        }
    finally:
        conn.close()


def _sync_post_comment_counts(conn: sqlite3.Connection) -> None:
    """Recompute channel_posts.comments_count from channel_comments."""
    try:
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(channel_comments)").fetchall()}
    except Exception:
        return
    if "channel_post_message_id" in cols:
        conn.execute(
            """
            UPDATE channel_posts
            SET comments_count = (
                SELECT COUNT(*) FROM channel_comments c
                WHERE c.channel_id = channel_posts.channel_id
                  AND c.channel_post_message_id = channel_posts.telegram_message_id
                  AND c.is_deleted = 0
            )
            """
        )
        # Orphan comments with channel_id but missing post id → attach to sole post.
        singles = conn.execute(
            """
            SELECT channel_id, telegram_message_id FROM channel_posts p
            WHERE (
                SELECT COUNT(*) FROM channel_posts p2 WHERE p2.channel_id = p.channel_id
            ) = 1
            """
        ).fetchall()
        for row in singles:
            ch_id, msg_id = int(row[0]), int(row[1])
            conn.execute(
                """
                UPDATE channel_comments
                SET channel_post_message_id = ?
                WHERE channel_id = ? AND channel_post_message_id IS NULL AND is_deleted = 0
                """,
                (msg_id, ch_id),
            )
            conn.execute(
                """
                UPDATE channel_posts
                SET comments_count = (
                    SELECT COUNT(*) FROM channel_comments c
                    WHERE c.channel_id = ? AND c.is_deleted = 0
                      AND (c.channel_post_message_id = ? OR c.channel_post_message_id IS NULL)
                )
                WHERE channel_id = ? AND telegram_message_id = ?
                """,
                (ch_id, msg_id, ch_id, msg_id),
            )
        conn.commit()
        return
    # Legacy DBs without channel_post_message_id: count by channel_id only.
    conn.execute(
        """
        UPDATE channel_posts
        SET comments_count = (
            SELECT COUNT(*) FROM channel_comments c
            WHERE c.channel_id = channel_posts.channel_id AND c.is_deleted = 0
        )
        """
    )
    conn.commit()


def growth_series(bot_id: int, days: int = 30, range_key: str | None = None) -> dict[str, Any]:
    key = (range_key or "").strip().lower()
    if key in ("24h", "1d", "today"):
        days = 1
    elif key in ("7d", "week"):
        days = 7
    elif key in ("30d", "month"):
        days = 30
    elif key in ("all", "all_time", "all-time"):
        days = 365
    days = max(1, min(int(days), 365))
    conn = connect_bot_db(bot_id)
    try:
        start = _day_start() - (days - 1) * 86400
        rows = conn.execute(
            """
            SELECT date(timestamp, 'unixepoch') AS d,
                   SUM(CASE WHEN event_type = 'join' THEN 1 ELSE 0 END) AS joins,
                   SUM(CASE WHEN event_type = 'leave' THEN 1 ELSE 0 END) AS leaves
            FROM channel_member_events
            WHERE timestamp >= ?
            GROUP BY d
            ORDER BY d
            """,
            (start,),
        ).fetchall()
        by_day = {str(r[0]): {"joins": int(r[1] or 0), "leaves": int(r[2] or 0)} for r in rows}
        series = []
        for i in range(days):
            day = datetime.fromtimestamp(start + i * 86400, tz=timezone.utc).strftime("%Y-%m-%d")
            item = by_day.get(day, {"joins": 0, "leaves": 0})
            series.append({"date": day, **item})
        return {"series": series, "days": days, "range": key or f"{days}d"}
    finally:
        conn.close()


def snapshot(bot_id: int, *, range_key: str = "30d") -> dict[str, Any]:
    """Single payload for live dashboard sync (local DB only — no network)."""
    ov = overview(bot_id)
    growth = growth_series(bot_id, range_key=range_key)
    hours = activity_hours(bot_id, days=14 if range_key != "24h" else 1)
    posts = top_posts(bot_id, limit=50)
    rules = get_rules(bot_id)
    # decay warnings opportunistically
    conn = connect_bot_db(bot_id)
    try:
        apply_warning_decay(conn, rules)
    finally:
        conn.close()
    comments = list_comments(bot_id, limit=120)
    restricted = list_restricted(bot_id)
    charts = {
        "reactions": reactions_breakdown(bot_id),
        "moderation": moderation_breakdown(bot_id),
        "top_posts_chart": top_posts(bot_id, limit=5),
    }
    revision = (
        f"{ov.get('joins_today')}-{ov.get('leaves_today')}-{ov.get('comments_moderated')}-"
        f"{len(comments.get('comments') or [])}-{len(restricted.get('users') or [])}-"
        f"{len(posts.get('posts') or [])}-{sum(c.get('count', 0) for c in charts['moderation'].get('slices') or [])}-"
        f"{ov.get('engagement_score')}-"
        f"{sum(int(p.get('views_count') or 0) for p in (posts.get('posts') or []))}"
    )
    return {
        "revision": revision,
        "range": range_key,
        "overview": ov,
        "growth": growth,
        "activity_hours": hours,
        "posts": posts,
        "rules": rules,
        "comments": comments,
        "restricted": restricted,
        "charts": charts,
        "synced_at": time.time(),
    }


def user_inspector(bot_id: int, user_id: int, chat_id: int | None = None) -> dict[str, Any]:
    rules = get_rules(bot_id)
    conn = connect_bot_db(bot_id)
    try:
        apply_warning_decay(conn, rules, chat_id=chat_id)
        uid = int(user_id)
        warn_q = "SELECT * FROM user_warnings WHERE user_id = ?"
        warn_args: list[Any] = [uid]
        if chat_id:
            warn_q += " AND chat_id = ?"
            warn_args.append(int(chat_id))
        warn_q += " ORDER BY last_warned_at DESC LIMIT 1"
        warn = conn.execute(warn_q, tuple(warn_args)).fetchone()

        comments_sql = """
            SELECT id, chat_id, channel_id, telegram_message_id, user_id, username,
                   text, is_deleted, moderated, violation_kind, created_at
            FROM channel_comments
            WHERE user_id = ?
        """
        c_args: list[Any] = [uid]
        if chat_id:
            comments_sql += " AND chat_id = ?"
            c_args.append(int(chat_id))
        comments_sql += " ORDER BY created_at DESC LIMIT 40"
        comments = conn.execute(comments_sql, tuple(c_args)).fetchall()

        join_row = conn.execute(
            """
            SELECT timestamp, invite_link_used, chat_id
            FROM channel_member_events
            WHERE user_id = ? AND event_type = 'join'
            ORDER BY timestamp ASC LIMIT 1
            """,
            (uid,),
        ).fetchone()

        actions = conn.execute(
            """
            SELECT action, reason, duration_minutes, created_at, chat_id
            FROM moderation_actions
            WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 30
            """,
            (uid,),
        ).fetchall()

        username = ""
        if warn:
            username = warn["username"] or ""
        elif comments:
            username = comments[0]["username"] or ""

        warn_count = int(warn["warning_count"]) if warn else 0
        last_warned = warn["last_warned_at"] if warn else None
        decay_hours = int(rules.get("warn_decay_hours") or 0)
        decay_expires_at = None
        decay_seconds_left = None
        if warn_count > 0 and last_warned and decay_hours > 0:
            decay_expires_at = float(last_warned) + decay_hours * 3600
            decay_seconds_left = max(0, int(decay_expires_at - time.time()))

        return {
            "user_id": uid,
            "username": username,
            "chat_id": int(chat_id) if chat_id else (int(warn["chat_id"]) if warn else (int(comments[0]["chat_id"]) if comments else 0)),
            "warning_count": warn_count,
            "last_reason": (warn["reason"] if warn else "") or "",
            "last_warned_at": last_warned,
            "warn_decay_hours": decay_hours,
            "decay_expires_at": decay_expires_at,
            "decay_seconds_left": decay_seconds_left,
            "joined_at": join_row["timestamp"] if join_row else None,
            "invite_link_used": join_row["invite_link_used"] if join_row else None,
            "comments": [
                {
                    "id": r["id"],
                    "chat_id": r["chat_id"],
                    "message_id": r["telegram_message_id"],
                    "text": r["text"] or "",
                    "is_deleted": bool(r["is_deleted"]),
                    "moderated": bool(r["moderated"]),
                    "violation_kind": r["violation_kind"] if "violation_kind" in r.keys() else None,
                    "created_at": r["created_at"],
                }
                for r in comments
            ],
            "actions": [
                {
                    "action": r["action"],
                    "reason": r["reason"],
                    "duration_minutes": r["duration_minutes"],
                    "created_at": r["created_at"],
                    "chat_id": r["chat_id"],
                }
                for r in actions
            ],
        }
    finally:
        conn.close()


def reactions_breakdown(bot_id: int) -> dict[str, Any]:
    conn = connect_bot_db(bot_id)
    try:
        rows = conn.execute(
            "SELECT reactions_json FROM channel_posts WHERE reactions_json IS NOT NULL AND reactions_json != ''"
        ).fetchall()
        totals: dict[str, int] = {}
        for r in rows:
            raw = r[0] if not isinstance(r, sqlite3.Row) else r["reactions_json"]
            try:
                data = json.loads(raw or "{}")
            except (TypeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            for emoji, count in data.items():
                totals[str(emoji)] = totals.get(str(emoji), 0) + int(count or 0)
        slices = [{"label": k, "count": v} for k, v in sorted(totals.items(), key=lambda x: -x[1])]
        if not slices:
            slices = [{"label": "—", "count": 0}]
        return {"slices": slices, "total": sum(s["count"] for s in slices)}
    finally:
        conn.close()


def moderation_breakdown(bot_id: int) -> dict[str, Any]:
    conn = connect_bot_db(bot_id)
    try:
        clean = conn.execute(
            "SELECT COUNT(*) FROM channel_comments WHERE moderated = 0 AND is_deleted = 0"
        ).fetchone()[0]
        warns = conn.execute(
            "SELECT COUNT(*) FROM moderation_actions WHERE action = 'warn'"
        ).fetchone()[0]
        mutes = conn.execute(
            "SELECT COUNT(*) FROM moderation_actions WHERE action = 'mute'"
        ).fetchone()[0]
        bans = conn.execute(
            "SELECT COUNT(*) FROM moderation_actions WHERE action = 'ban'"
        ).fetchone()[0]
        slices = [
            {"label": "clean", "count": int(clean or 0)},
            {"label": "warn", "count": int(warns or 0)},
            {"label": "mute", "count": int(mutes or 0)},
            {"label": "ban", "count": int(bans or 0)},
        ]
        return {"slices": slices, "total": sum(s["count"] for s in slices)}
    finally:
        conn.close()


def delete_comment(bot_id: int, *, chat_id: int, message_id: int, user_id: int = 0, username: str = "") -> dict[str, Any]:
    return manual_action(
        bot_id,
        action="delete",
        chat_id=chat_id,
        user_id=user_id or 0,
        username=username,
        reason="Manual delete",
        message_id=message_id,
    )


def clear_user_warnings(bot_id: int, chat_id: int, user_id: int) -> dict[str, Any]:
    conn = connect_bot_db(bot_id)
    try:
        conn.execute(
            "UPDATE user_warnings SET warning_count = 0, reason = NULL WHERE chat_id = ? AND user_id = ?",
            (int(chat_id), int(user_id)),
        )
        conn.commit()
        _log_action(
            conn,
            chat_id=int(chat_id),
            channel_id=None,
            user_id=int(user_id),
            username=str(user_id),
            action="clear_warnings",
            reason="Manual clear",
        )
        return {"ok": True, "action": "clear_warnings"}
    finally:
        conn.close()


def activity_hours(bot_id: int, days: int = 14) -> dict[str, Any]:
    days = max(1, min(int(days), 90))
    conn = connect_bot_db(bot_id)
    try:
        start = time.time() - days * 86400
        rows = conn.execute(
            """
            SELECT CAST(strftime('%H', created_at, 'unixepoch') AS INTEGER) AS h, COUNT(*)
            FROM channel_comments
            WHERE created_at >= ? AND is_deleted = 0
            GROUP BY h
            """,
            (start,),
        ).fetchall()
        counts = {int(r[0]): int(r[1] or 0) for r in rows}
        hours = [{"hour": h, "count": counts.get(h, 0)} for h in range(24)]
        return {"hours": hours, "days": days}
    finally:
        conn.close()


def top_posts(bot_id: int, limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(int(limit), 200))
    from backend.core.channel_hub_store import build_post_url

    conn = connect_bot_db(bot_id)
    try:
        # Prefer username from registry for public links
        usernames = {
            int(r["chat_id"]): (r["username"] or "")
            for r in conn.execute(
                "SELECT chat_id, username FROM channel_registry WHERE chat_type = 'channel'"
            ).fetchall()
        }
        _sync_post_comment_counts(conn)
        rows = conn.execute(
            """
            SELECT id, channel_id, telegram_message_id, text, full_text, post_url,
                   views_count, comments_count, reactions_count, created_at
            FROM channel_posts
            WHERE channel_id IN (
                SELECT chat_id FROM channel_registry
                WHERE chat_type = 'channel'
                  AND (IFNULL(username, '') != '' OR members_count IS NOT NULL)
            )
            ORDER BY (views_count + comments_count * 5 + reactions_count * 2) DESC,
                     views_count DESC, comments_count DESC, reactions_count DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        posts = []
        for r in rows:
            views = int(r["views_count"] or 0)
            comments = int(r["comments_count"] or 0)
            reactions = int(r["reactions_count"] or 0)
            engagement = views + comments * 5 + reactions * 2
            full = (r["full_text"] if "full_text" in r.keys() else None) or (r["text"] or "")
            channel_id = int(r["channel_id"])
            message_id = int(r["telegram_message_id"])
            url = (r["post_url"] if "post_url" in r.keys() else None) or build_post_url(
                channel_id, message_id, usernames.get(channel_id)
            )
            posts.append(
                {
                    "id": r["id"],
                    "channel_id": channel_id,
                    "chat_id": channel_id,
                    "message_id": message_id,
                    "telegram_message_id": message_id,
                    "post_url": url,
                    "text": (full or "")[:120],
                    "full_text": full or "",
                    "views_count": views,
                    "comments_count": comments,
                    "reactions_count": reactions,
                    "engagement": engagement,
                    "created_at": r["created_at"],
                }
            )
        return {"posts": posts}
    finally:
        conn.close()


def list_comments(bot_id: int, limit: int = 100) -> dict[str, Any]:
    limit = max(1, min(int(limit), 300))
    conn = connect_bot_db(bot_id)
    try:
        rows = conn.execute(
            """
            SELECT id, chat_id, channel_id, telegram_message_id, user_id, username,
                   text, is_deleted, moderated, violation_kind, created_at
            FROM channel_comments
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return {
            "comments": [
                {
                    "id": r["id"],
                    "chat_id": r["chat_id"],
                    "channel_id": r["channel_id"],
                    "message_id": r["telegram_message_id"],
                    "user_id": r["user_id"],
                    "username": r["username"],
                    "text": r["text"] or "",
                    "is_deleted": bool(r["is_deleted"]),
                    "moderated": bool(r["moderated"]),
                    "violation_kind": r["violation_kind"] if "violation_kind" in r.keys() else None,
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        }
    finally:
        conn.close()


def list_restricted(bot_id: int) -> dict[str, Any]:
    conn = connect_bot_db(bot_id)
    try:
        rows = conn.execute(
            """
            SELECT a.id, a.chat_id, a.channel_id, a.user_id, a.username, a.action,
                   a.reason, a.duration_minutes, a.created_at
            FROM moderation_actions a
            WHERE a.action IN ('mute', 'ban')
              AND a.id = (
                  SELECT MAX(b.id) FROM moderation_actions b
                  WHERE b.chat_id = a.chat_id AND b.user_id = a.user_id
                    AND b.action IN ('mute', 'ban', 'unban')
              )
              AND a.action IN ('mute', 'ban')
            ORDER BY a.created_at DESC
            LIMIT 200
            """
        ).fetchall()
        return {
            "users": [
                {
                    "id": r["id"],
                    "chat_id": r["chat_id"],
                    "channel_id": r["channel_id"],
                    "user_id": r["user_id"],
                    "username": r["username"],
                    "action": r["action"],
                    "reason": r["reason"],
                    "duration_minutes": r["duration_minutes"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        }
    finally:
        conn.close()


def get_rules(bot_id: int, channel_id: int = 0) -> dict[str, Any]:
    conn = connect_bot_db(bot_id)
    try:
        return get_moderation_rules(conn, channel_id)
    finally:
        conn.close()


def update_rules(bot_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    conn = connect_bot_db(bot_id)
    try:
        return save_moderation_rules(conn, payload)
    finally:
        conn.close()


def _log_action(
    conn: sqlite3.Connection,
    *,
    chat_id: int,
    channel_id: int | None,
    user_id: int | None,
    username: str | None,
    action: str,
    reason: str,
    duration_minutes: int | None = None,
    message_id: int | None = None,
    source: str = "manual",
) -> None:
    conn.execute(
        """
        INSERT INTO moderation_actions
        (chat_id, channel_id, user_id, username, action, reason, duration_minutes, message_id, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(chat_id),
            int(channel_id) if channel_id is not None else None,
            int(user_id) if user_id is not None else None,
            username,
            action,
            reason,
            duration_minutes,
            message_id,
            source,
            time.time(),
        ),
    )
    conn.commit()


def _bump_warning(conn: sqlite3.Connection, chat_id: int, user_id: int, username: str, reason: str) -> int:
    row = conn.execute(
        "SELECT warning_count FROM user_warnings WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id),
    ).fetchone()
    count = int(row[0] if row else 0) + 1
    conn.execute(
        """
        INSERT INTO user_warnings (chat_id, user_id, username, warning_count, reason, last_warned_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            username = excluded.username,
            warning_count = excluded.warning_count,
            reason = excluded.reason,
            last_warned_at = excluded.last_warned_at
        """,
        (chat_id, user_id, username, count, reason, time.time()),
    )
    conn.commit()
    return count


def _reset_warnings(conn: sqlite3.Connection, chat_id: int, user_id: int) -> None:
    conn.execute(
        "UPDATE user_warnings SET warning_count = 0, reason = NULL WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id),
    )
    conn.commit()


def manual_action(
    bot_id: int,
    *,
    action: str,
    chat_id: int,
    user_id: int,
    username: str = "",
    reason: str = "",
    duration_minutes: int | None = None,
    message_id: int | None = None,
    channel_id: int | None = None,
) -> dict[str, Any]:
    action = (action or "").strip().lower()
    if action not in {"warn", "mute", "ban", "unban", "delete", "clear_warnings"}:
        raise ChannelHubError(f"Unknown action: {action}")
    if action == "clear_warnings":
        return clear_user_warnings(bot_id, chat_id, user_id)
    token = _load_token(bot_id)
    conn = connect_bot_db(bot_id)
    try:
        rules = get_moderation_rules(conn, int(channel_id or 0))
        uname = (username or "").strip() or str(user_id)
        result: dict[str, Any] = {"ok": True, "action": action}

        if action == "delete" and message_id:
            _tg(token, "deleteMessage", {"chat_id": chat_id, "message_id": message_id})
            conn.execute(
                """UPDATE channel_comments SET is_deleted = 1, moderated = 1
                   WHERE chat_id = ? AND telegram_message_id = ?""",
                (chat_id, message_id),
            )
            conn.commit()
            _log_action(
                conn,
                chat_id=chat_id,
                channel_id=channel_id,
                user_id=user_id,
                username=uname,
                action="delete",
                reason=reason or "Manual delete",
                message_id=message_id,
            )
            return result

        if action == "warn":
            count = _bump_warning(conn, chat_id, user_id, uname, reason or "Manual warning")
            max_w = int(rules.get("max_warnings") or 3)
            try:
                _tg(
                    token,
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text": f"@{uname} Warned ({count}/{max_w}). Reason: {reason or 'Manual warning'}.",
                    },
                )
            except ChannelHubError:
                pass
            _log_action(
                conn,
                chat_id=chat_id,
                channel_id=channel_id,
                user_id=user_id,
                username=uname,
                action="warn",
                reason=reason or "Manual warning",
                message_id=message_id,
            )
            result["warning_count"] = count
            if rules.get("instant_mute_on_warn"):
                minutes = int(rules.get("instant_mute_duration_minutes") or 10)
                until = int(time.time()) + minutes * 60
                try:
                    _tg(
                        token,
                        "restrictChatMember",
                        {
                            "chat_id": chat_id,
                            "user_id": user_id,
                            "permissions": {
                                "can_send_messages": False,
                                "can_send_audios": False,
                                "can_send_documents": False,
                                "can_send_photos": False,
                                "can_send_videos": False,
                                "can_send_video_notes": False,
                                "can_send_voice_notes": False,
                                "can_send_polls": False,
                                "can_send_other_messages": False,
                                "can_add_web_page_previews": False,
                            },
                            "until_date": until,
                        },
                    )
                    _log_action(
                        conn,
                        chat_id=chat_id,
                        channel_id=channel_id,
                        user_id=user_id,
                        username=uname,
                        action="mute",
                        reason="Instant mute on warn",
                        duration_minutes=minutes,
                    )
                except ChannelHubError:
                    pass
            if count >= max_w:
                return manual_action(
                    bot_id,
                    action="mute" if not rules.get("mute_permanent") else "ban",
                    chat_id=chat_id,
                    user_id=user_id,
                    username=uname,
                    reason="Max warnings reached",
                    duration_minutes=int(rules.get("mute_duration_minutes") or 60),
                    channel_id=channel_id,
                )
            return result

        if action == "unban":
            _tg(
                token,
                "restrictChatMember",
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "permissions": {
                        "can_send_messages": True,
                        "can_send_audios": True,
                        "can_send_documents": True,
                        "can_send_photos": True,
                        "can_send_videos": True,
                        "can_send_video_notes": True,
                        "can_send_voice_notes": True,
                        "can_send_polls": True,
                        "can_send_other_messages": True,
                        "can_add_web_page_previews": True,
                    },
                },
            )
            try:
                _tg(token, "unbanChatMember", {"chat_id": chat_id, "user_id": user_id, "only_if_banned": True})
            except ChannelHubError:
                pass
            _reset_warnings(conn, chat_id, user_id)
            _log_action(
                conn,
                chat_id=chat_id,
                channel_id=channel_id,
                user_id=user_id,
                username=uname,
                action="unban",
                reason=reason or "Manual unban",
            )
            return result

        if action == "ban":
            _tg(token, "banChatMember", {"chat_id": chat_id, "user_id": user_id})
            _reset_warnings(conn, chat_id, user_id)
            _log_action(
                conn,
                chat_id=chat_id,
                channel_id=channel_id,
                user_id=user_id,
                username=uname,
                action="ban",
                reason=reason or "Manual ban",
                duration_minutes=None,
            )
            return result

        # mute
        minutes = int(duration_minutes if duration_minutes is not None else (rules.get("mute_duration_minutes") or 60))
        until = 0 if minutes <= 0 else int(time.time()) + minutes * 60
        _tg(
            token,
            "restrictChatMember",
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "permissions": {
                    "can_send_messages": False,
                    "can_send_audios": False,
                    "can_send_documents": False,
                    "can_send_photos": False,
                    "can_send_videos": False,
                    "can_send_video_notes": False,
                    "can_send_voice_notes": False,
                    "can_send_polls": False,
                    "can_send_other_messages": False,
                    "can_add_web_page_previews": False,
                },
                "until_date": until,
            },
        )
        _reset_warnings(conn, chat_id, user_id)
        _log_action(
            conn,
            chat_id=chat_id,
            channel_id=channel_id,
            user_id=user_id,
            username=uname,
            action="mute",
            reason=reason or "Manual mute",
            duration_minutes=minutes if minutes > 0 else None,
        )
        result["duration_minutes"] = minutes
        return result
    finally:
        conn.close()
