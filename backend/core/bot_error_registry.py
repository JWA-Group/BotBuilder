"""In-memory ring buffer of bot runtime node errors for BotCopilot self-healing."""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque
from typing import Any

# Redact secrets before anything reaches LLM / monitor detail.
_SECRET_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|token|password|passwd|secret|authorization|bearer|cookie|session)",
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|token|password)\s*[:=]\s*[\"']?[^\s\"']+",
)
_TELEGRAM_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*")
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")

MAX_ERRORS_PER_BOT = 20


def redact_text(text: str, *, max_len: int = 12000) -> str:
    if not text:
        return ""
    out = str(text)
    out = _SECRET_VALUE_RE.sub(r"\1: [REDACTED]", out)
    out = _TELEGRAM_TOKEN_RE.sub("[REDACTED_BOT_TOKEN]", out)
    out = _BEARER_RE.sub("Bearer [REDACTED]", out)
    out = _SK_RE.sub("[REDACTED_KEY]", out)
    if len(out) > max_len:
        out = out[: max_len - 1] + "…"
    return out


def redact_mapping(obj: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "[truncated]"
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in list(obj.items())[:40]:
            key = str(k)
            if _SECRET_KEY_RE.search(key):
                out[key] = "[REDACTED]"
            else:
                out[key] = redact_mapping(v, depth=depth + 1)
        return out
    if isinstance(obj, list):
        return [redact_mapping(x, depth=depth + 1) for x in obj[:30]]
    if isinstance(obj, str):
        return redact_text(obj, max_len=800)
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    return redact_text(str(obj), max_len=400)


def normalize_error_event(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    bot_id = raw.get("bot_id")
    if bot_id is None:
        return None
    snap = raw.get("local_variables_snapshot")
    if not isinstance(snap, dict):
        snap = {}
    event = {
        "bot_id": str(bot_id),
        "user_id": raw.get("user_id"),
        "failing_node_id": str(raw.get("failing_node_id") or raw.get("node_id") or ""),
        "node_type": str(raw.get("node_type") or ""),
        "exception_type": str(raw.get("exception_type") or "Exception"),
        "stack_trace": redact_text(str(raw.get("stack_trace") or ""), max_len=10000),
        "local_variables_snapshot": redact_mapping(snap),
        "message": redact_text(str(raw.get("message") or ""), max_len=500),
        "ts": float(raw.get("ts") or time.time()),
    }
    if not event["message"]:
        event["message"] = (
            f"{event['exception_type']} in node "
            f"{event['failing_node_id'] or '?'} ({event['node_type'] or '?'})"
        )
    return event


class BotErrorRegistry:
    """Thread-safe per-bot ring buffer (last N runtime errors)."""

    def __init__(self, maxlen: int = MAX_ERRORS_PER_BOT) -> None:
        self._maxlen = max(1, int(maxlen))
        self._lock = threading.Lock()
        self._by_bot: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=self._maxlen)
        )

    def push(self, event: dict[str, Any] | None) -> dict[str, Any] | None:
        normalized = normalize_error_event(event)
        if not normalized:
            return None
        key = normalized["bot_id"]
        with self._lock:
            buf = self._by_bot[key]
            if buf:
                last = buf[-1]
                if (
                    last.get("failing_node_id") == normalized.get("failing_node_id")
                    and last.get("exception_type") == normalized.get("exception_type")
                    and abs(float(last.get("ts") or 0) - float(normalized.get("ts") or 0)) < 2.5
                ):
                    return last
            buf.append(normalized)
        try:
            from backend.core.monitor import log_hub

            detail_parts = [
                f"node_id: {normalized['failing_node_id']}",
                f"node_type: {normalized['node_type']}",
                f"exception: {normalized['exception_type']}",
                f"user_id: {normalized.get('user_id')}",
                "--- stack ---",
                normalized["stack_trace"][:8000],
            ]
            snap = normalized.get("local_variables_snapshot") or {}
            if snap:
                detail_parts.append("--- locals (redacted) ---")
                detail_parts.append(str(snap)[:2000])
            log_hub.emit(
                f"Runtime error · node {normalized['failing_node_id'] or '?'} · {normalized['exception_type']}",
                layer="ERROR",
                bot_id=key,
                detail="\n".join(detail_parts),
            )
        except Exception:
            pass
        return normalized

    def get_recent_errors(
        self,
        bot_id: str | int | None,
        *,
        limit: int = MAX_ERRORS_PER_BOT,
    ) -> list[dict[str, Any]]:
        if bot_id is None:
            return []
        key = str(bot_id).strip()
        if not key:
            return []
        with self._lock:
            items = list(self._by_bot.get(key) or [])
        if limit and limit > 0:
            items = items[-int(limit) :]
        return items

    def clear(self, bot_id: str | int | None = None) -> int:
        with self._lock:
            if bot_id is None:
                n = sum(len(v) for v in self._by_bot.values())
                self._by_bot.clear()
                return n
            key = str(bot_id).strip()
            n = len(self._by_bot.get(key) or [])
            self._by_bot.pop(key, None)
            return n

    def format_for_prompt(
        self,
        bot_id: str | int | None,
        *,
        limit: int = 8,
    ) -> str:
        errors = self.get_recent_errors(bot_id, limit=limit)
        if not errors:
            return "(none)"
        lines: list[str] = []
        for i, err in enumerate(reversed(errors), 1):
            lines.append(
                f"{i}. node_id={err.get('failing_node_id')!s} "
                f"type={err.get('node_type')!s} "
                f"exc={err.get('exception_type')!s} "
                f"user={err.get('user_id')!s}"
            )
            stack = (err.get("stack_trace") or "").strip()
            if stack:
                # Keep last frames — most relevant for node handlers
                stack_lines = stack.splitlines()
                tail = "\n".join(stack_lines[-18:])
                lines.append(tail)
            snap = err.get("local_variables_snapshot")
            if snap:
                lines.append(f"locals: {snap}")
            lines.append("---")
        return "\n".join(lines)


# Process-wide singleton (FastAPI sidecar)
bot_error_registry = BotErrorRegistry()


def try_parse_runtime_error_log_line(text: str) -> dict[str, Any] | None:
    """Parse `BB_RUNTIME_ERROR:{json}` marker lines from bot.log."""
    if not text:
        return None
    marker = "BB_RUNTIME_ERROR:"
    idx = text.find(marker)
    if idx < 0:
        return None
    raw_json = text[idx + len(marker) :].strip()
    if not raw_json:
        return None
    import json

    try:
        data = json.loads(raw_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
