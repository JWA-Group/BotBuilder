"""
Bot process orchestration using the bundled embedded Python interpreter.

Customer bot scripts (projects/bot_*/main.py) run via .\\python_embed\\python.exe
so they do not depend on a globally installed system Python.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]


def _projects_dir() -> Path:
    raw = (os.environ.get("BOTBUILDER_DATA_DIR") or "").strip()
    if raw:
        return Path(raw) / "projects"
    return ROOT / "projects"


def _app_root() -> Path:
    raw = (os.environ.get("BOTBUILDER_APP_ROOT") or "").strip()
    if raw:
        return Path(raw)
    return ROOT


PROJECTS_DIR = _projects_dir()
EMBED_PYTHON = _app_root() / "python_embed" / "python.exe"


def resolve_embedded_python() -> str:
    """Prefer bundled embed, then project venv.

    Never use a frozen PyInstaller sidecar exe to run bot scripts.
    In desktop / packaged mode never fall back to a random system Python
    (it usually has no aiogram) — fail with a clear error instead.
    """
    desktop = os.environ.get("DESKTOP_APP", "").strip() in ("1", "true", "yes")
    frozen = getattr(sys, "frozen", False)

    candidates: list[Path] = [
        _app_root() / "python_embed" / "python.exe",
    ]
    if frozen:
        exe_dir = Path(sys.executable).resolve().parent
        # resources/botbuilder-backend → resources/app/python_embed
        candidates.extend(
            [
                exe_dir.parent / "app" / "python_embed" / "python.exe",
                _app_root() / "venv" / "Scripts" / "python.exe",
                exe_dir.parent / "app" / "venv" / "Scripts" / "python.exe",
            ]
        )
    else:
        candidates.append(_app_root() / "venv" / "Scripts" / "python.exe")

    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.stat().st_size > 1024:
                return str(candidate)
        except OSError:
            continue

    if desktop or frozen:
        raise FileNotFoundError(
            "Не найден встроенный Python для ботов (python_embed/python.exe с aiogram). "
            "Пересоберите установщик: npm run build:prod"
        )

    return sys.executable


def bot_dir(projects_dir: Path, bot_id: int) -> Path:
    return projects_dir / f"bot_{bot_id}"


def pid_path(projects_dir: Path, bot_id: int) -> Path:
    return bot_dir(projects_dir, bot_id) / "run.pid"


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            still_active = 259
            alive = bool(
                kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                and exit_code.value == still_active
            )
            kernel32.CloseHandle(handle)
            return alive
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_pid(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


class BotRunner:
    """Spawns and tracks customer bot subprocesses."""

    def __init__(self, projects_dir: Optional[Path] = None):
        self.projects_dir = Path(projects_dir or PROJECTS_DIR)
        self.python_exe = resolve_embedded_python()
        self.running_bots: Dict[int, subprocess.Popen] = {}
        self._lock = threading.RLock()

    def is_running(self, bot_id: int) -> bool:
        """True when a tracked or pid-file process is alive."""
        with self._lock:
            return self.get_running_pid(bot_id) is not None

    def restart_bot(self, bot_id: int, *, platform: str = "telegram") -> dict[str, Any]:
        """
        Hot reload: if the bot process is active, terminate it, wait for exit,
        then launch main.py again. No-op when the bot is stopped.
        """
        with self._lock:
            if not self.is_running(bot_id):
                return {"restarted": False, "running": False}

            self.terminate(bot_id)
            # Brief pause so Long Poll / Telegram sessions release cleanly (Windows).
            time.sleep(0.35)

            workdir = bot_dir(self.projects_dir, bot_id)
            stderr_log = workdir / "stderr.log"
            launcher_log = workdir / "launcher.log"
            try:
                process = self.start(
                    bot_id,
                    stderr_log=stderr_log,
                    launcher_log=launcher_log,
                    platform=platform,
                )
            except Exception as exc:
                return {
                    "restarted": False,
                    "running": False,
                    "error": str(exc),
                    "was_running": True,
                }

            self.running_bots[bot_id] = process
            self.write_pid(bot_id, process.pid)
            return {
                "restarted": True,
                "running": True,
                "pid": process.pid,
                "platform": platform,
                "was_running": True,
            }

    def get_running_pid(self, bot_id: int) -> int | None:
        proc = self.running_bots.get(bot_id)
        if proc is not None:
            if proc.poll() is None:
                return proc.pid
            del self.running_bots[bot_id]

        return self._read_pid_file(bot_id)

    def write_pid(self, bot_id: int, pid: int) -> None:
        path = pid_path(self.projects_dir, bot_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(pid), encoding="utf-8")

    def clear_pid(self, bot_id: int) -> None:
        try:
            pid_path(self.projects_dir, bot_id).unlink(missing_ok=True)
        except OSError:
            pass

    def terminate(self, bot_id: int) -> None:
        with self._lock:
            proc = self.running_bots.pop(bot_id, None)
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

            pid = self._read_pid_file(bot_id)
            if pid:
                kill_pid(pid)
            self.clear_pid(bot_id)

    def _read_pid_file(self, bot_id: int) -> int | None:
        path = pid_path(self.projects_dir, bot_id)
        if not path.is_file():
            return None
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        if process_alive(pid):
            return pid
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    def terminate_all(self) -> int:
        stopped = 0
        for bot_id in list(self.running_bots.keys()):
            self.terminate(bot_id)
            stopped += 1

        if self.projects_dir.is_dir():
            for entry in self.projects_dir.iterdir():
                if not entry.is_dir() or not entry.name.startswith("bot_"):
                    continue
                try:
                    bot_id = int(entry.name.split("_", 1)[1])
                except (IndexError, ValueError):
                    continue
                if self.get_running_pid(bot_id):
                    self.terminate(bot_id)
                    stopped += 1
        return stopped

    def start(
        self,
        bot_id: int,
        *,
        stderr_log: Path,
        launcher_log: Path,
        platform: str,
    ) -> subprocess.Popen:
        """Launch bot main.py with the embedded Python interpreter."""
        workdir = bot_dir(self.projects_dir, bot_id)
        main_py = workdir / "main.py"
        if not main_py.is_file():
            raise FileNotFoundError("main.py не найден")

        launcher_log.parent.mkdir(parents=True, exist_ok=True)
        with launcher_log.open("a", encoding="utf-8") as logf:
            logf.write(
                f"\n--- start bot_id={bot_id} platform={platform} python={self.python_exe} ---\n"
            )
            logf.flush()

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        try:
            import urllib.request

            for scheme, proxy_url in urllib.request.getproxies().items():
                if proxy_url:
                    env[f"{scheme.upper()}_PROXY"] = proxy_url
        except Exception:
            pass

        stderr_log.parent.mkdir(parents=True, exist_ok=True)
        err_file = stderr_log.open("a", encoding="utf-8")
        creationflags = 0
        if os.name == "nt":
            # Hide the console window; keep a separate process group for clean stop.
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags |= subprocess.CREATE_NO_WINDOW
        process = subprocess.Popen(
            [self.python_exe, "-u", "main.py"],
            cwd=str(workdir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=err_file,
            env=env,
            creationflags=creationflags,
        )
        err_file.close()
        return process


# Shared singleton used by FastAPI routes
bot_runner = BotRunner()
