"""In-memory progress log and cancel flags for running BotCopilot requests."""

from __future__ import annotations

import threading
import time
from typing import Any

_TTL_SECONDS = 1800
_MAX_EVENTS = 300

_lock = threading.Lock()
_runs: dict[str, dict[str, Any]] = {}


class AgentCancelled(Exception):
    """Raised inside the agent loop when the user pressed Stop."""


def _prune(now: float) -> None:
    stale = [rid for rid, r in _runs.items() if now - r["updated"] > _TTL_SECONDS]
    for rid in stale:
        _runs.pop(rid, None)


def start(request_id: str | None) -> None:
    if not request_id:
        return
    now = time.time()
    with _lock:
        _prune(now)
        _runs[request_id] = {
            "events": [],
            "cancelled": False,
            "done": False,
            "started": now,
            "updated": now,
        }


def emit(request_id: str | None, text: str, *, kind: str = "step") -> None:
    if not request_id:
        return
    now = time.time()
    with _lock:
        run = _runs.get(request_id)
        if run is None:
            return
        run["events"].append({"seq": len(run["events"]), "t": round(now - run["started"], 1),
                              "kind": kind, "text": str(text)[:300]})
        del run["events"][:-_MAX_EVENTS]
        run["updated"] = now


def finish(request_id: str | None) -> None:
    if not request_id:
        return
    with _lock:
        run = _runs.get(request_id)
        if run is not None:
            run["done"] = True
            run["updated"] = time.time()


def cancel(request_id: str) -> bool:
    with _lock:
        run = _runs.get(request_id)
        if run is None or run["done"]:
            return False
        run["cancelled"] = True
        run["updated"] = time.time()
    emit(request_id, "Остановка по запросу пользователя...", kind="cancel")
    return True


def is_cancelled(request_id: str | None) -> bool:
    if not request_id:
        return False
    with _lock:
        run = _runs.get(request_id)
        return bool(run and run["cancelled"])


def snapshot(request_id: str, after: int = -1) -> dict[str, Any]:
    with _lock:
        run = _runs.get(request_id)
        if run is None:
            return {"found": False, "events": [], "done": True, "cancelled": False}
        events = [e for e in run["events"] if e["seq"] > after]
        return {
            "found": True,
            "events": events,
            "done": run["done"],
            "cancelled": run["cancelled"],
            "elapsed": round(time.time() - run["started"], 1),
        }
