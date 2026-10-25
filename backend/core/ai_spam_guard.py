"""Zero-token anti-spam + exact-match response cache for AI Director."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from typing import Any, Optional, Tuple

# Defaults match the product brief
RATE_LIMIT_WINDOW_SEC = 5.0
RATE_LIMIT_MAX_MSG = 3
DEDUP_WINDOW_SEC = 10 * 60  # 10 minutes

_RATE_LIMIT_REPLY = (
    "Слишком много сообщений подряд. Подождите несколько секунд и попробуйте снова."
)


def _hash_message(message_text: str) -> str:
    normalized = (message_text or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class AISpamGuard:
    """
    SQLite-backed spam / duplicate guard.

    Tables live in the bot's ``user_data.db`` (or any path passed to the ctor):
      - ai_spam_events(user_id, ts)           — rate limit window
      - ai_spam_cache(user_id, msg_hash, ...) — exact-match command cache
    """

    def __init__(
        self,
        db_path: str,
        *,
        rate_window_sec: float = RATE_LIMIT_WINDOW_SEC,
        rate_max: int = RATE_LIMIT_MAX_MSG,
        dedup_window_sec: float = DEDUP_WINDOW_SEC,
    ) -> None:
        self.db_path = db_path
        self.rate_window_sec = float(rate_window_sec)
        self.rate_max = int(rate_max)
        self.dedup_window_sec = float(dedup_window_sec)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ai_spam_events (
                        user_id INTEGER NOT NULL,
                        ts REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ai_spam_events_user_ts "
                    "ON ai_spam_events(user_id, ts)"
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ai_spam_cache (
                        user_id INTEGER NOT NULL,
                        msg_hash TEXT NOT NULL,
                        message_text TEXT NOT NULL DEFAULT '',
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        created_at REAL NOT NULL,
                        PRIMARY KEY (user_id, msg_hash)
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ai_spam_cache_created "
                    "ON ai_spam_cache(created_at)"
                )
                conn.commit()
            finally:
                conn.close()

    def is_spam_or_duplicate(
        self,
        user_id: int,
        message_text: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Returns ``(blocked, cached_payload_json_or_rate_limit_text)``.

        * Rate limit: > ``rate_max`` messages in ``rate_window_sec`` → spam.
        * Exact hash match within ``dedup_window_sec`` → return cached JSON string
          (command payload), no LLM call.
        """
        uid = int(user_id or 0)
        if not uid:
            return False, None
        now = time.time()
        msg_hash = _hash_message(message_text)

        with self._lock:
            conn = self._connect()
            try:
                # 1) Rate limit
                cutoff = now - self.rate_window_sec
                conn.execute(
                    "DELETE FROM ai_spam_events WHERE user_id = ? AND ts < ?",
                    (uid, cutoff),
                )
                conn.execute(
                    "INSERT INTO ai_spam_events (user_id, ts) VALUES (?, ?)",
                    (uid, now),
                )
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM ai_spam_events WHERE user_id = ? AND ts >= ?",
                    (uid, cutoff),
                ).fetchone()
                count = int(row["c"] if row else 0)
                conn.commit()
                if count > self.rate_max:
                    return True, _RATE_LIMIT_REPLY

                # 2) Exact-match cache
                cached = conn.execute(
                    """
                    SELECT payload_json, created_at FROM ai_spam_cache
                    WHERE user_id = ? AND msg_hash = ?
                    """,
                    (uid, msg_hash),
                ).fetchone()
                if cached:
                    age = now - float(cached["created_at"] or 0)
                    if age <= self.dedup_window_sec:
                        payload = cached["payload_json"] or ""
                        return True, payload if payload else "{}"
                    conn.execute(
                        "DELETE FROM ai_spam_cache WHERE user_id = ? AND msg_hash = ?",
                        (uid, msg_hash),
                    )
                    conn.commit()
            finally:
                conn.close()
        return False, None

    def cache_response(
        self,
        user_id: int,
        message_text: str,
        command_payload: dict[str, Any] | None,
    ) -> None:
        """Store JSON command payload against message hash for this user."""
        uid = int(user_id or 0)
        if not uid:
            return
        msg_hash = _hash_message(message_text)
        payload = command_payload if isinstance(command_payload, dict) else {}
        try:
            blob = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            blob = "{}"
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO ai_spam_cache
                        (user_id, msg_hash, message_text, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (uid, msg_hash, (message_text or "")[:2000], blob, now),
                )
                # Opportunistic prune older than 2x dedup window
                conn.execute(
                    "DELETE FROM ai_spam_cache WHERE created_at < ?",
                    (now - self.dedup_window_sec * 2,),
                )
                conn.commit()
            finally:
                conn.close()

    def clear_user(self, user_id: int) -> None:
        uid = int(user_id or 0)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM ai_spam_events WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM ai_spam_cache WHERE user_id = ?", (uid,))
                conn.commit()
            finally:
                conn.close()


def get_spam_guard(db_path: str) -> AISpamGuard:
    """Factory used by bot runtime and tests."""
    return AISpamGuard(db_path)


# ---------------------------------------------------------------------------
# Injected into generated bot main.py (uses USER_DB_PATH at runtime)
# ---------------------------------------------------------------------------

AI_SPAM_GUARD_RUNTIME = r'''
class AISpamGuard:
    """In-bot anti-spam + exact-match cache (user_data.db)."""

    RATE_WINDOW = 5.0
    RATE_MAX = 3
    DEDUP_WINDOW = 600.0
    RATE_REPLY = "Слишком много сообщений подряд. Подождите несколько секунд и попробуйте снова."

    def __init__(self, db_path=None):
        import sqlite3
        import threading
        self.db_path = db_path or USER_DB_PATH
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS ai_spam_events (user_id INTEGER NOT NULL, ts REAL NOT NULL)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ai_spam_events_user_ts ON ai_spam_events(user_id, ts)"
                )
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS ai_spam_cache (
                        user_id INTEGER NOT NULL,
                        msg_hash TEXT NOT NULL,
                        message_text TEXT NOT NULL DEFAULT '',
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        created_at REAL NOT NULL,
                        PRIMARY KEY (user_id, msg_hash)
                    )"""
                )
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _hash(message_text):
        import hashlib
        return hashlib.sha256((message_text or "").strip().encode("utf-8")).hexdigest()

    def is_spam_or_duplicate(self, user_id, message_text):
        import time
        uid = int(user_id or 0)
        if not uid:
            return False, None
        now = time.time()
        msg_hash = self._hash(message_text)
        with self._lock:
            conn = self._connect()
            try:
                cutoff = now - self.RATE_WINDOW
                conn.execute("DELETE FROM ai_spam_events WHERE user_id = ? AND ts < ?", (uid, cutoff))
                conn.execute("INSERT INTO ai_spam_events (user_id, ts) VALUES (?, ?)", (uid, now))
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM ai_spam_events WHERE user_id = ? AND ts >= ?",
                    (uid, cutoff),
                ).fetchone()
                count = int(row["c"] if row else 0)
                conn.commit()
                if count > self.RATE_MAX:
                    return True, self.RATE_REPLY
                cached = conn.execute(
                    "SELECT payload_json, created_at FROM ai_spam_cache WHERE user_id = ? AND msg_hash = ?",
                    (uid, msg_hash),
                ).fetchone()
                if cached:
                    age = now - float(cached["created_at"] or 0)
                    if age <= self.DEDUP_WINDOW:
                        return True, cached["payload_json"] or "{}"
                    conn.execute(
                        "DELETE FROM ai_spam_cache WHERE user_id = ? AND msg_hash = ?",
                        (uid, msg_hash),
                    )
                    conn.commit()
            finally:
                conn.close()
        return False, None

    def cache_response(self, user_id, message_text, command_payload):
        import json
        import time
        uid = int(user_id or 0)
        if not uid:
            return
        msg_hash = self._hash(message_text)
        payload = command_payload if isinstance(command_payload, dict) else {}
        try:
            blob = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            blob = "{}"
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO ai_spam_cache
                       (user_id, msg_hash, message_text, payload_json, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (uid, msg_hash, (message_text or "")[:2000], blob, now),
                )
                conn.execute(
                    "DELETE FROM ai_spam_cache WHERE created_at < ?",
                    (now - self.DEDUP_WINDOW * 2,),
                )
                conn.commit()
            finally:
                conn.close()


def get_ai_spam_guard():
    return AISpamGuard(USER_DB_PATH)
'''


def ensure_ai_spam_guard_runtime(code: str) -> str:
    """Inject AISpamGuard into compiled bot main.py if missing."""
    if "class AISpamGuard:" in code and "def get_ai_spam_guard(" in code:
        return code
    anchor = "\n\n\ndef log_activity("
    insert_at = code.find(anchor)
    if insert_at < 0:
        # Fallback: append before plugin definitions marker
        marker = "__PLUGIN_HANDLER_DEFINITIONS__"
        if marker in code:
            return code.replace(
                marker,
                AI_SPAM_GUARD_RUNTIME.strip() + "\n\n" + marker,
                1,
            )
        return code
    return code[:insert_at] + "\n\n" + AI_SPAM_GUARD_RUNTIME.strip() + code[insert_at:]

