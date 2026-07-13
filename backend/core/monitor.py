"""System monitor: resource metrics, process control, centralized log aggregation."""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore

from backend.core.app_paths import PROJECTS_DIR

_BOT_DIR_RE = re.compile(r"bot_(\d+)", re.I)

# Strict cadence: log SSE batches and hardware sampling.
LOG_FLUSH_INTERVAL_SEC = 0.5
METRICS_POLL_INTERVAL_SEC = 2.0
METRICS_IDLE_INTERVAL_SEC = 12.0
SSE_KEEPALIVE_SEC = 15.0


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class LogPacket:
    timestamp: str
    layer: str
    bot_id: str | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "layer": self.layer,
            "bot_id": self.bot_id,
            "message": self.message,
        }


class LogHub:
    """Thread-safe hub with asyncio.Queue subscribers and 500ms batch flush."""

    MAX_HISTORY = 1500
    MAX_SUBSCRIBER_QUEUE = 2000

    def __init__(self) -> None:
        self._history: deque[LogPacket] = deque(maxlen=self.MAX_HISTORY)
        self._subscribers: list[asyncio.Queue[LogPacket]] = []
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    def emit(
        self,
        message: str,
        *,
        layer: str = "API",
        bot_id: int | str | None = None,
    ) -> LogPacket:
        text = (message or "").strip()
        if not text:
            return LogPacket(_utc_iso(), "API", None, "")
        layer_norm = (layer or "API").upper()
        if layer_norm not in ("API", "LLM", "BOT", "ERROR"):
            layer_norm = "API"
        bid = str(bot_id) if bot_id is not None else None
        packet = LogPacket(_utc_iso(), layer_norm, bid, text)
        with self._lock:
            self._history.append(packet)
            subscribers = list(self._subscribers)
        for sub in subscribers:
            self._enqueue_packet(sub, packet)
        return packet

    def _enqueue_packet(self, sub: asyncio.Queue[LogPacket], packet: LogPacket) -> None:
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
                self._loop = loop
            except RuntimeError:
                return

        def _put() -> None:
            try:
                sub.put_nowait(packet)
            except asyncio.QueueFull:
                try:
                    sub.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    sub.put_nowait(packet)
                except asyncio.QueueFull:
                    pass

        try:
            if loop.is_running():
                loop.call_soon_threadsafe(_put)
            else:
                _put()
        except RuntimeError:
            pass

    def subscribe_async(self, *, replay: int = 80) -> asyncio.Queue[LogPacket]:
        q: asyncio.Queue[LogPacket] = asyncio.Queue(maxsize=self.MAX_SUBSCRIBER_QUEUE)
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        with self._lock:
            self._subscribers.append(q)
            replay_packets = list(self._history)[-replay:]
        for packet in replay_packets:
            try:
                q.put_nowait(packet)
            except asyncio.QueueFull:
                break
        return q

    def unsubscribe_async(self, q: asyncio.Queue[LogPacket]) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def history(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            return [p.to_dict() for p in list(self._history)[-limit:]]

    def clear(self) -> int:
        """Drop ring-buffer history and drain live subscriber queues."""
        with self._lock:
            cleared = len(self._history)
            self._history.clear()
            subscribers = list(self._subscribers)
        for sub in subscribers:
            self._drain_queue(sub)
        return cleared

    def _drain_queue(self, sub: asyncio.Queue[LogPacket]) -> None:
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
                self._loop = loop
            except RuntimeError:
                return

        def _drain() -> None:
            while True:
                try:
                    sub.get_nowait()
                except asyncio.QueueEmpty:
                    break

        try:
            if loop.is_running():
                loop.call_soon_threadsafe(_drain)
            else:
                _drain()
        except RuntimeError:
            pass

    async def iter_batched_sse(
        self,
        *,
        replay: int = 80,
        flush_interval: float = LOG_FLUSH_INTERVAL_SEC,
        keepalive_sec: float = SSE_KEEPALIVE_SEC,
    ) -> AsyncGenerator[str, None]:
        """Flush accumulated logs as a JSON array every flush_interval; skip empty ticks."""
        import json

        q = self.subscribe_async(replay=replay)
        idle = 0.0
        try:
            while True:
                await asyncio.sleep(flush_interval)
                batch: list[dict[str, Any]] = []
                while True:
                    try:
                        packet = q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    batch.append(packet.to_dict())
                if batch:
                    idle = 0.0
                    yield f"data: {json.dumps(batch, ensure_ascii=False)}\n\n"
                else:
                    idle += flush_interval
                    if idle >= keepalive_sec:
                        idle = 0.0
                        yield ": keepalive\n\n"
        finally:
            self.unsubscribe_async(q)


log_hub = LogHub()

# Paths that poll frequently — never log individually (reduces monitor lag).
_SKIP_API_LOG_RE = (
    re.compile(r"^/api/monitor/"),
    re.compile(r"^/api/bots/status/\d+$"),
    re.compile(r"^/api/health$"),
    re.compile(r"^/api/analytics/"),
)


def _normalize_api_path(path: str) -> str:
    path = (path or "").split("?", 1)[0]
    for pattern, repl in (
        (r"/api/bots/status/\d+", "/api/bots/status/:id"),
        (r"/api/scenario/history/\d+", "/api/scenario/history/:id"),
        (r"/api/projects/\d+/history", "/api/projects/:id/history"),
        (r"/api/projects/\d+", "/api/projects/:id"),
        (r"/api/bots/\d+", "/api/bots/:id"),
    ):
        path = re.sub(pattern, repl, path)
    return path


def _should_skip_api_log(method: str, path: str) -> bool:
    if any(rx.match(path) for rx in _SKIP_API_LOG_RE):
        return True
    return False


class _ApiLogBatcher:
    """Aggregate burst API calls into one line (e.g. status ×11)."""

    def __init__(self, flush_ms: float = 0.85) -> None:
        self._flush_ms = flush_ms
        self._lock = threading.Lock()
        self._buckets: dict[str, list[int]] = {}
        self._timer: threading.Timer | None = None

    def record(self, method: str, path: str, status_code: int, ms: int) -> None:
        if _should_skip_api_log(method, path):
            return
        norm = _normalize_api_path(path)
        key = f"{method} {norm} → {status_code}"
        with self._lock:
            self._buckets.setdefault(key, []).append(ms)
            if self._timer is None:
                self._timer = threading.Timer(self._flush_ms, self._flush)
                self._timer.daemon = True
                self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            buckets = self._buckets
            self._buckets = {}
            self._timer = None
        for key, times in buckets.items():
            n = len(times)
            avg = sum(times) // max(n, 1)
            if n == 1:
                log_hub.emit(f"{key} ({times[0]}ms)", layer="API")
            else:
                log_hub.emit(f"{key} ×{n} (ср. {avg}ms)", layer="API")


_api_log_batcher = _ApiLogBatcher()

# Heavy work only while the monitor UI is open (avoids lag across the app).
_monitor_stream_clients = 0
_monitor_last_touch: float = 0.0
_MONITOR_IDLE_SEC = 50.0

_metrics_lock = threading.Lock()
_metrics_cache: dict[str, Any] = {
    "timestamp": "",
    "cpu_percent": 0.0,
    "memory_mb": 0.0,
    "main": {"pid": 0, "cpu_percent": 0.0, "memory_mb": 0.0},
    "children": [],
    "process_count": 1,
    "bot_count": 0,
    "psutil_ok": psutil is not None,
}
_sampler_stop = threading.Event()
_sampler_thread: threading.Thread | None = None
_tailer: "_BotLogTailer | None" = None

_bot_pids_cache: dict[int, int] = {}
_bot_pids_cache_ts: float = 0.0
_last_psutil_scan: float = 0.0
_BOT_PIDS_CACHE_TTL = 5.0
_BOT_PIDS_SCAN_INTERVAL = 15.0
_cpu_logical_count: int = 1


def monitor_touch() -> None:
    global _monitor_last_touch
    now = time.monotonic()
    was_idle = _monitor_stream_clients == 0 and (
        _monitor_last_touch == 0.0 or (now - _monitor_last_touch) >= _MONITOR_IDLE_SEC
    )
    _monitor_last_touch = now
    if was_idle:
        _schedule_metrics_refresh()


def _schedule_metrics_refresh() -> None:
    def _run() -> None:
        try:
            data = _compute_resource_metrics()
            with _metrics_lock:
                _metrics_cache.clear()
                _metrics_cache.update(data)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True, name="monitor-refresh").start()


def monitor_stream_connected() -> None:
    global _monitor_stream_clients
    _monitor_stream_clients += 1
    monitor_touch()


def monitor_stream_disconnected() -> None:
    global _monitor_stream_clients
    _monitor_stream_clients = max(0, _monitor_stream_clients - 1)


def monitor_is_watched() -> bool:
    if _monitor_stream_clients > 0:
        return True
    return (time.monotonic() - _monitor_last_touch) < _MONITOR_IDLE_SEC


class MonitorAPIMiddleware:
    """Log meaningful /api/* requests; skip/aggregate noisy polling."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        if not monitor_is_watched():
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        if method == "GET" and _should_skip_api_log(method, path):
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            ms = int((time.perf_counter() - start) * 1000)
            if status_code >= 500:
                log_hub.emit(f"{method} {path} → {status_code} ({ms}ms)", layer="ERROR")
            else:
                _api_log_batcher.record(method, path, status_code, ms)


_cpu_track: dict[int, Any] = {}


def _safe_process(pid: int):
    if psutil is None or pid <= 0:
        return None
    try:
        return psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def _tracked_process(pid: int):
    """Cache Process handles and prime cpu_percent with a non-blocking sample."""
    proc = _cpu_track.get(pid)
    if proc is not None:
        try:
            if proc.is_running():
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        _cpu_track.pop(pid, None)
    proc = _safe_process(pid)
    if proc is not None:
        _cpu_track[pid] = proc
        try:
            # Non-blocking prime: first call returns 0.0, subsequent use delta.
            proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return proc


def _memory_mb_win32(pid: int) -> float:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    access = 0x0400 | 0x0010  # QUERY_INFORMATION | VM_READ
    handle = kernel32.OpenProcess(access, False, pid)
    if not handle:
        return 0.0
    try:

        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        pmc = PROCESS_MEMORY_COUNTERS_EX()
        pmc.cb = ctypes.sizeof(pmc)
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
            return round(pmc.WorkingSetSize / (1024 * 1024), 1)
    finally:
        kernel32.CloseHandle(handle)
    return 0.0


def _memory_mb_for_pid(pid: int) -> float:
    if pid <= 0:
        return 0.0
    if psutil is not None:
        proc = _safe_process(pid)
        if proc is not None:
            try:
                with proc.oneshot():
                    return round(proc.memory_info().rss / (1024 * 1024), 1)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    if os.name == "nt":
        return _memory_mb_win32(pid)
    return 0.0


def _cpu_count() -> int:
    global _cpu_logical_count
    if psutil is not None:
        try:
            _cpu_logical_count = max(1, int(psutil.cpu_count(logical=True) or 1))
        except Exception:
            pass
    return _cpu_logical_count


def _read_cpu_percent(pid: int) -> float:
    proc = _tracked_process(pid)
    if proc is None:
        return 0.0
    try:
        raw = max(0.0, proc.cpu_percent(interval=None))
        return round(raw / _cpu_count(), 1)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        _cpu_track.pop(pid, None)
        return 0.0


def _read_proc_stats(pid: int) -> dict[str, float]:
    mem = _memory_mb_for_pid(pid)
    return {"memory_mb": mem, "cpu_percent": _read_cpu_percent(pid)}


def _collect_bot_pids_fast() -> dict[int, int]:
    """Fast path: BotRunner + run.pid only (no full PC process scan)."""
    from core.runner import bot_runner, process_alive

    mapping: dict[int, int] = {}

    for bot_id, proc in list(bot_runner.running_bots.items()):
        if proc.poll() is None:
            mapping[bot_id] = proc.pid

    if PROJECTS_DIR.is_dir():
        for entry in PROJECTS_DIR.iterdir():
            if not entry.is_dir() or not entry.name.startswith("bot_"):
                continue
            try:
                bot_id = int(entry.name.split("_", 1)[1])
            except (IndexError, ValueError):
                continue
            if bot_id in mapping:
                continue
            pid_file = entry / "run.pid"
            if not pid_file.is_file():
                continue
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
            if process_alive(pid):
                mapping[bot_id] = pid

    return mapping


def _collect_bot_pids(*, allow_psutil_scan: bool = False) -> dict[int, int]:
    """Resolve bot_id → pid; full PC scan only on a slow timer when monitor is open."""
    global _bot_pids_cache, _bot_pids_cache_ts, _last_psutil_scan

    now = time.monotonic()
    mapping = _collect_bot_pids_fast()

    if now - _bot_pids_cache_ts < _BOT_PIDS_CACHE_TTL:
        mapping = {**_bot_pids_cache, **mapping}
        return mapping

    if (
        allow_psutil_scan
        and monitor_is_watched()
        and psutil is not None
        and now - _last_psutil_scan >= _BOT_PIDS_SCAN_INTERVAL
    ):
        for bot_id, pid in _scan_bot_pids_psutil().items():
            mapping.setdefault(bot_id, pid)
        _last_psutil_scan = now

    _bot_pids_cache = dict(mapping)
    _bot_pids_cache_ts = now
    return mapping


def _scan_bot_pids_psutil() -> dict[int, int]:
    found: dict[int, int] = {}
    if psutil is None:
        return found

    projects_key = str(PROJECTS_DIR).replace("\\", "/").lower()
    for proc in psutil.process_iter(["pid", "cmdline", "name"]):
        try:
            info = proc.info
            pid = info.get("pid")
            cmdline = info.get("cmdline") or []
            joined = " ".join(str(p) for p in cmdline).replace("\\", "/").lower()
            cwd_norm = ""
            try:
                cwd_norm = proc.cwd().replace("\\", "/").lower()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

            in_projects = projects_key in joined or cwd_norm.startswith(projects_key)
            if not in_projects or "main.py" not in joined:
                continue

            bot_id = None
            m = _BOT_DIR_RE.search(cwd_norm)
            if m:
                bot_id = int(m.group(1))
            if bot_id is None:
                for part in cmdline:
                    m = _BOT_DIR_RE.search(str(part).replace("\\", "/"))
                    if m:
                        bot_id = int(m.group(1))
                        break
            if bot_id is not None and pid:
                found[bot_id] = pid
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            continue
    return found


def find_bot_id_by_pid(pid: int) -> int | None:
    for bot_id, bp in _collect_bot_pids().items():
        if bp == pid:
            return bot_id
    return None


def _read_bot_name(bot_id: int) -> str:
    config = PROJECTS_DIR / f"bot_{bot_id}" / "config.json"
    if config.is_file():
        try:
            import json

            data = json.loads(config.read_text(encoding="utf-8"))
            name = (data.get("name") or data.get("bot_name") or "").strip()
            if name:
                return name
        except Exception:
            pass
    return f"Bot #{bot_id}"


def _compute_resource_metrics() -> dict[str, Any]:
    """Sample CPU/RAM for server + bots. Never blocks the event loop (runs in thread)."""
    main_pid = os.getpid()
    main_stats = {"memory_mb": 0.0, "cpu_percent": 0.0}
    children_stats: list[dict[str, Any]] = []
    bots_mem = 0.0
    bots_cpu = 0.0
    other_mem = 0.0

    _cpu_count()
    bot_pids = _collect_bot_pids(allow_psutil_scan=True)
    bot_pid_set = set(bot_pids.values())

    if psutil is not None:
        # Prime handles once; cpu_percent(interval=None) is non-blocking.
        all_pids = [main_pid, *bot_pids.values()]
        for pid in all_pids:
            _tracked_process(pid)

        main_stats = _read_proc_stats(main_pid)
        main_mem = main_stats["memory_mb"]

        for bot_id, pid in bot_pids.items():
            st = _read_proc_stats(pid)
            if st["memory_mb"] <= 0:
                st = {**st, "memory_mb": _memory_mb_for_pid(pid)}
            bots_mem += st["memory_mb"]
            bots_cpu += st["cpu_percent"]
            children_stats.append({"pid": pid, "bot_id": bot_id, **st})

        main_proc = _safe_process(main_pid)
        if main_proc:
            try:
                for child in main_proc.children(recursive=True):
                    cpid = child.pid
                    if cpid in bot_pid_set or cpid == main_pid:
                        continue
                    other_mem += _memory_mb_for_pid(cpid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        total_mem = round(main_mem + bots_mem + other_mem, 1)
        total_cpu = round(min(100.0, main_stats["cpu_percent"] + bots_cpu), 1)
        bot_count = len(bot_pids)
        process_count = 1 + bot_count
    else:
        bot_count = len(bot_pids)
        process_count = 1 + bot_count
        total_mem = 0.0
        total_cpu = 0.0
        other_mem = 0.0

    return {
        "timestamp": _utc_iso(),
        "cpu_percent": total_cpu,
        "memory_mb": total_mem,
        "bots_memory_mb": round(bots_mem, 1),
        "bots_cpu_percent": round(min(100.0, bots_cpu), 1),
        "other_memory_mb": round(other_mem, 1),
        "main": {"pid": main_pid, **main_stats},
        "children": children_stats,
        "process_count": process_count,
        "bot_count": bot_count,
        "psutil_ok": psutil is not None,
        "monitor_active": monitor_is_watched(),
    }


def _metrics_sampler_loop() -> None:
    """Background thread: poll hardware every 2s while monitor UI is open."""
    while not _sampler_stop.is_set():
        interval = (
            METRICS_POLL_INTERVAL_SEC if monitor_is_watched() else METRICS_IDLE_INTERVAL_SEC
        )
        try:
            if monitor_is_watched():
                data = _compute_resource_metrics()
                with _metrics_lock:
                    _metrics_cache.clear()
                    _metrics_cache.update(data)
        except Exception as exc:
            if monitor_is_watched():
                log_hub.emit(f"Metrics sampler: {exc}", layer="ERROR")
        _sampler_stop.wait(interval)


def get_resource_metrics() -> dict[str, Any]:
    with _metrics_lock:
        return dict(_metrics_cache)


def list_running_processes() -> list[dict[str, Any]]:
    from backend.utils.generate_main import get_bot_platform

    metrics = get_resource_metrics()
    cpu_by_bot: dict[int, float] = {}
    mem_by_bot: dict[int, float] = {}
    for child in metrics.get("children") or []:
        bid = child.get("bot_id")
        if bid is not None:
            cpu_by_bot[int(bid)] = float(child.get("cpu_percent") or 0)
            mem_by_bot[int(bid)] = float(child.get("memory_mb") or 0)

    rows: list[dict[str, Any]] = []
    for bot_id, pid in _collect_bot_pids().items():
        mem = mem_by_bot.get(bot_id) or _memory_mb_for_pid(pid)
        cpu = cpu_by_bot.get(bot_id, 0.0)
        uptime = 0
        proc = _safe_process(pid)
        if proc:
            try:
                uptime = max(0, int(time.time() - proc.create_time()))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        rows.append(
            {
                "bot_id": bot_id,
                "name": _read_bot_name(bot_id),
                "pid": pid,
                "memory_mb": round(mem, 1),
                "cpu_percent": round(cpu, 1),
                "uptime_seconds": uptime,
                "platform": get_bot_platform(bot_id),
            }
        )
    rows.sort(key=lambda r: r["bot_id"])
    return rows


def kill_process_by_pid(pid: int) -> dict[str, Any]:
    bot_id = find_bot_id_by_pid(pid)
    if bot_id is not None:
        from core.runner import bot_runner

        bot_runner.terminate(bot_id)
        log_hub.emit(f"Bot #{bot_id} остановлен (pid={pid})", layer="API", bot_id=bot_id)
        return {"ok": True, "action": "kill", "pid": pid, "bot_id": bot_id}

    if psutil is None:
        return {"ok": False, "error": "psutil required for unknown PID", "pid": pid}
    proc = _safe_process(pid)
    if proc is None:
        return {"ok": False, "error": "Process not found", "pid": pid}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except psutil.TimeoutExpired:
        proc.kill()
    log_hub.emit(f"Процесс {pid} остановлен", layer="API")
    return {"ok": True, "action": "kill", "pid": pid}


async def restart_bot_process(pid: int) -> dict[str, Any]:
    import asyncio

    from core.runner import bot_runner
    from backend.utils.generate_main import generate_main_py, get_bot_platform

    bot_id = find_bot_id_by_pid(pid)
    if bot_id is None:
        return {"ok": False, "error": "PID is not a managed bot process", "pid": pid}

    platform = get_bot_platform(bot_id)
    bot_runner.terminate(bot_id)
    await asyncio.sleep(0.4)

    bot_dir = PROJECTS_DIR / f"bot_{bot_id}"
    try:
        generate_main_py(bot_id)
        process = bot_runner.start(
            bot_id,
            stderr_log=bot_dir / "stderr.log",
            launcher_log=bot_dir / "launcher.log",
            platform=platform,
        )
    except Exception as exc:
        log_hub.emit(f"Restart bot #{bot_id} failed: {exc}", layer="ERROR", bot_id=bot_id)
        return {"ok": False, "error": str(exc), "bot_id": bot_id}

    bot_runner.running_bots[bot_id] = process
    bot_runner.write_pid(bot_id, process.pid)
    log_hub.emit(f"Bot #{bot_id} перезапущен (pid={process.pid})", layer="API", bot_id=bot_id)
    return {
        "ok": True,
        "action": "restart",
        "bot_id": bot_id,
        "pid": process.pid,
        "platform": platform,
    }


class _BotLogTailer(threading.Thread):
    """Tail bot.log / stderr.log only for running bots (new lines only)."""

    def __init__(self, projects_dir: Path) -> None:
        super().__init__(daemon=True, name="monitor-bot-tail")
        self._projects = projects_dir
        self._offsets: dict[str, int] = {}
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.wait(3.0):
            if not monitor_is_watched():
                continue
            try:
                self._scan()
            except Exception as exc:
                log_hub.emit(f"Bot tailer: {exc}", layer="ERROR")

    def _scan(self) -> None:
        active = set(_collect_bot_pids().keys())
        if not active:
            return
        for bot_id in active:
            bot_dir = self._projects / f"bot_{bot_id}"
            if not bot_dir.is_dir():
                continue
            self._tail_file(bot_dir / "bot.log", bot_id, default_layer="BOT")
            self._tail_file(bot_dir / "stderr.log", bot_id, default_layer="ERROR")

    def _tail_file(self, path: Path, bot_id: int, *, default_layer: str) -> None:
        key = str(path)
        if not path.is_file():
            self._offsets.pop(key, None)
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        if key not in self._offsets:
            self._offsets[key] = size
            return
        offset = self._offsets[key]
        if size < offset:
            offset = 0
        if size <= offset:
            return
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(offset)
                chunk = fh.read(65536)
                self._offsets[key] = fh.tell()
        except OSError:
            return
        emitted = 0
        for line in chunk.splitlines():
            if emitted >= 12:
                break
            text = line.strip()
            if not text:
                continue
            layer = default_layer
            low = text.lower()
            if "traceback" in low or "error" in low or "exception" in low:
                layer = "ERROR"
            log_hub.emit(text, layer=layer, bot_id=bot_id)
            emitted += 1


def start_monitor_services() -> None:
    global _tailer, _sampler_thread
    try:
        log_hub.bind_loop(asyncio.get_running_loop())
    except RuntimeError:
        pass
    if psutil is None:
        log_hub.emit(
            "WARN: psutil не найден в venv — установите: venv\\Scripts\\pip install psutil",
            layer="ERROR",
        )
    if _sampler_thread is None or not _sampler_thread.is_alive():
        _sampler_stop.clear()
        _sampler_thread = threading.Thread(
            target=_metrics_sampler_loop, daemon=True, name="monitor-metrics"
        )
        _sampler_thread.start()
    if _tailer is None or not _tailer.is_alive():
        _tailer = _BotLogTailer(PROJECTS_DIR)
        _tailer.start()


def stop_monitor_services() -> None:
    global _tailer, _sampler_thread
    _sampler_stop.set()
    if _tailer is not None:
        _tailer.stop()
        _tailer = None
    _sampler_thread = None
    log_hub.emit("Центр мониторинга остановлен", layer="API")


def emit_llm(message: str, *, bot_id: int | None = None) -> None:
    log_hub.emit(message, layer="LLM", bot_id=bot_id)


def log_api(message: str, *, bot_id: int | None = None, error: bool = False) -> None:
    log_hub.emit(message, layer="ERROR" if error else "API", bot_id=bot_id)
