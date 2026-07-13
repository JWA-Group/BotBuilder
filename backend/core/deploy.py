"""Remote SSH deployment via Docker (isolated from host Python/OS)."""

from __future__ import annotations

import io
import os
import queue
import re
import shlex
import stat as stat_module
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.app_paths import get_logs_dir
from backend.core.deploy_bundle import PERSISTENT_REMOTE_FILES, collect_project_files
from backend.utils.generate_main import BASE_DIR, generate_main_from_scenario

try:
    from core.runner import bot_runner
except ImportError:  # pragma: no cover
    bot_runner = None  # type: ignore

try:
    import paramiko
except ImportError:  # pragma: no cover
    paramiko = None  # type: ignore

DEPLOY_ENGINE_VERSION = "3.4-docker"
REMOTE_ROOT = "/opt/bot_builder"
DEPLOY_LOGS_DIR = get_logs_dir() / "deploy_logs"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_COMPOSE_DETECT = (
    "if docker compose version >/dev/null 2>&1; then "
    "  COMPOSE='docker compose'; "
    "elif command -v docker-compose >/dev/null 2>&1; then "
    "  COMPOSE='docker-compose'; "
    "else "
    "  echo 'ERROR: Docker Compose not found'; exit 1; "
    "fi"
)

_INIT_SQLITE_SCRIPT = (
    "import sqlite3; "
    "c=sqlite3.connect('/w/user_data.db'); "
    "c.executescript("
    "'CREATE TABLE IF NOT EXISTS users (tg_user_id INTEGER PRIMARY KEY, tg_user_name TEXT, tg_user_date REAL NOT NULL);"
    "CREATE TABLE IF NOT EXISTS user_data (user_id INTEGER NOT NULL, field TEXT NOT NULL, value TEXT, updated_at REAL, PRIMARY KEY (user_id, field));"
    "CREATE INDEX IF NOT EXISTS idx_user_data_user ON user_data(user_id);"
    "CREATE TABLE IF NOT EXISTS activity_log (user_id INTEGER NOT NULL, event_time REAL NOT NULL, event_type TEXT);"
    "CREATE INDEX IF NOT EXISTS idx_activity_user_time ON activity_log(user_id, event_time);'); "
    "c.commit(); c.close()"
)

# Installs Docker if missing, ensures daemon is running, prints compose version.
_DOCKER_BOOTSTRAP_SCRIPT = r"""set -e
export DEBIAN_FRONTEND=noninteractive
if command -v docker >/dev/null 2>&1; then
  echo "Docker уже установлен: $(docker --version)"
else
  echo "Установка Docker (get.docker.com)…"
  curl -fsSL https://get.docker.com | sh
fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl enable docker 2>/dev/null || true
  systemctl start docker 2>/dev/null || true
fi
docker --version
if docker compose version >/dev/null 2>&1; then
  docker compose version
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose --version
else
  echo "ERROR: Docker Compose не найден после установки Docker"
  exit 1
fi
"""


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


@dataclass
class DeployLogBroker:
    """Thread-safe log queue + on-disk log file for sharing full output."""

    job_id: str
    bot_id: int
    log_path: Path
    queue: queue.Queue = field(default_factory=queue.Queue)
    done: bool = False
    success: bool = False
    error: str | None = None
    _file_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"# BotBuilder deploy log\n"
            f"# engine: {DEPLOY_ENGINE_VERSION}\n"
            f"# job_id: {self.job_id}\n"
            f"# bot_id: {self.bot_id}\n"
            f"# started: {datetime.utcnow().isoformat()}Z\n\n"
        )
        self.log_path.write_text(header, encoding="utf-8")

    def log(self, line: str) -> None:
        text = _strip_ansi((line or "").rstrip("\r\n"))
        if not text:
            return
        self.queue.put({"type": "log", "line": text, "ts": time.time()})
        with self._file_lock:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(text + "\n")

    def finish(self, success: bool, error: str | None = None) -> None:
        self.success = success
        self.error = error
        self.done = True
        summary = "SUCCESS" if success else f"FAILED: {error or 'unknown'}"
        self.log(f"--- {summary} ---")
        latest = DEPLOY_LOGS_DIR / f"bot_{self.bot_id}_latest.log"
        try:
            latest.write_text(self.log_path.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass
        self.queue.put(
            {
                "type": "done",
                "success": success,
                "error": error,
                "log_file": str(self.log_path),
                "log_download": f"/api/projects/{self.bot_id}/deploy/logs/{self.job_id}",
                "ts": time.time(),
            }
        )


_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def create_deploy_job(bot_id: int) -> tuple[str, DeployLogBroker]:
    job_id = str(uuid.uuid4())
    DEPLOY_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DEPLOY_LOGS_DIR / f"{job_id}.log"
    broker = DeployLogBroker(job_id=job_id, bot_id=bot_id, log_path=log_path)
    with _jobs_lock:
        _jobs[job_id] = {
            "bot_id": bot_id,
            "broker": broker,
            "started": time.time(),
            "log_path": str(log_path),
        }
    return job_id, broker


def get_deploy_job(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def list_deploy_logs(bot_id: int, limit: int = 20) -> list[dict[str, Any]]:
    DEPLOY_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for path in sorted(DEPLOY_LOGS_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.name.endswith("_latest.log"):
            continue
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:400]
        except OSError:
            head = ""
        if f"# bot_id: {bot_id}\n" not in head:
            continue
        job_id = path.stem
        entries.append(
            {
                "job_id": job_id,
                "path": str(path),
                "modified": path.stat().st_mtime,
                "download": f"/api/projects/{bot_id}/deploy/logs/{job_id}",
            }
        )
        if len(entries) >= limit:
            break
    return entries


def get_deploy_log_path(job_id: str) -> Path | None:
    path = DEPLOY_LOGS_DIR / f"{job_id}.log"
    return path if path.is_file() else None


def get_latest_deploy_log_path(bot_id: int) -> Path | None:
    path = DEPLOY_LOGS_DIR / f"bot_{bot_id}_latest.log"
    return path if path.is_file() else None


def _require_paramiko() -> None:
    if paramiko is None:
        raise RuntimeError("paramiko не установлен. Выполните: pip install paramiko")


def _connect_ssh(
    host: str,
    username: str,
    *,
    password: str | None,
    ssh_private_key: str | None,
    port: int,
):
    _require_paramiko()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    pkey = None
    if ssh_private_key and ssh_private_key.strip():
        key_io = io.StringIO(ssh_private_key.strip())
        for key_cls in (
            paramiko.RSAKey,
            paramiko.ECDSAKey,
            paramiko.Ed25519Key,
        ):
            try:
                key_io.seek(0)
                pkey = key_cls.from_private_key(key_io)
                break
            except Exception:
                continue
        if pkey is None:
            raise ValueError("Не удалось прочитать SSH private key")

    if not password and not pkey:
        raise ValueError("Укажите password или ssh_private_key")

    client.connect(
        hostname=host.strip(),
        port=port,
        username=username.strip(),
        password=password or None,
        pkey=pkey,
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    return client


def _run_remote(client, command: str, broker: DeployLogBroker, *, ignore_fail: bool = False) -> int:
    broker.log(f"$ {command}")
    _stdin, stdout, stderr = client.exec_command(command, get_pty=True)
    channel = stdout.channel

    while not channel.exit_status_ready():
        if channel.recv_ready():
            chunk = channel.recv(4096).decode("utf-8", errors="replace")
            for line in chunk.splitlines():
                broker.log(line)
        if channel.recv_stderr_ready():
            err_chunk = channel.recv_stderr(4096).decode("utf-8", errors="replace")
            for line in err_chunk.splitlines():
                broker.log(line)
        time.sleep(0.05)

    while channel.recv_ready():
        chunk = channel.recv(4096).decode("utf-8", errors="replace")
        for line in chunk.splitlines():
            broker.log(line)

    exit_code = channel.recv_exit_status()
    err_tail = stderr.read().decode("utf-8", errors="replace").strip()
    if err_tail:
        for line in err_tail.splitlines():
            broker.log(line)

    if exit_code != 0 and not ignore_fail:
        raise RuntimeError(f"Команда завершилась с кодом {exit_code}")
    return exit_code


def _ensure_docker(client, broker: DeployLogBroker) -> None:
    broker.log(f"Deploy engine v{DEPLOY_ENGINE_VERSION}: проверка Docker и Compose…")
    _run_remote(client, _DOCKER_BOOTSTRAP_SCRIPT, broker)


def _remote_file_exists(sftp, path: str) -> bool:
    try:
        return stat_module.S_ISREG(sftp.stat(path).st_mode)
    except OSError:
        return False


def _upload_project(client, bot_id: int, remote_dir: str, broker: DeployLogBroker) -> None:
    generate_main_from_scenario(bot_id)
    files = collect_project_files(bot_id)
    sftp = client.open_sftp()

    def ensure_remote_dir(path: str) -> None:
        parts = [p for p in path.split("/") if p]
        current = ""
        for part in parts:
            current += "/" + part
            try:
                sftp.stat(current)
            except OSError:
                sftp.mkdir(current)

    ensure_remote_dir(remote_dir)
    ensure_remote_dir(f"{remote_dir}/data")
    ensure_remote_dir(f"{remote_dir}/media")

    for rel, content in files.items():
        rel_posix = rel.replace("\\", "/")
        if rel_posix in PERSISTENT_REMOTE_FILES:
            remote_path = f"{remote_dir}/data/{rel_posix}"
            legacy_path = f"{remote_dir}/{rel_posix}"
            if _remote_file_exists(sftp, remote_path) or _remote_file_exists(sftp, legacy_path):
                broker.log(f"⊘ data/{rel_posix} (данные на сервере сохранены)")
                continue
            broker.log(f"↑ data/{rel_posix}")
        else:
            remote_path = f"{remote_dir}/{rel_posix}"
            broker.log(f"↑ {rel_posix}")

        parent = str(Path(remote_path).parent).replace("\\", "/")
        ensure_remote_dir(parent)
        with sftp.file(remote_path, "wb") as remote_file:
            if isinstance(content, str):
                remote_file.write(content.encode("utf-8"))
            else:
                remote_file.write(content)

    sftp.close()


def _stop_local_bot(bot_id: int, broker: DeployLogBroker) -> None:
    """Telegram allows only one polling connection — stop local instance before cloud deploy."""
    if bot_runner is None:
        broker.log("WARN: bot_runner недоступен — проверьте, что локальный бот остановлен вручную.")
        pid_file = Path(BASE_DIR) / f"bot_{bot_id}" / "run.pid"
        if pid_file.is_file():
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
                broker.log(f"Найден run.pid={pid}, останавливаем процесс…")
                if os.name == "nt":
                    import subprocess
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/F"],
                        capture_output=True,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                else:
                    os.kill(pid, 15)
                pid_file.unlink(missing_ok=True)
                broker.log("Локальный процесс остановлен (run.pid).")
                time.sleep(1.5)
            except Exception as exc:
                broker.log(f"WARN: не удалось остановить по run.pid: {exc}")
        return
    try:
        if bot_runner.get_running_pid(bot_id):
            broker.log(f"Останавливаем локальный bot_{bot_id} (конфликт polling с облаком)…")
            bot_runner.terminate(bot_id)
            time.sleep(1.5)
            broker.log("Локальный бот остановлен.")
    except Exception as exc:
        broker.log(f"WARN: не удалось остановить локальный бот: {exc}")


_HEALTH_POLLING_RE = (
    "Start polling|Run polling|Слушаем Long Poll|Long Poll готов"
)
_HEALTH_ERR_RE = (
    "IndentationError|SyntaxError|ModuleNotFoundError|Invalid token|"
    "TelegramUnauthorized|IsADirectoryError|Conflict.*getUpdates|"
    "Bot stopped|SystemExit|Таймаут подключения к Telegram"
)


def _check_telegram_reachability(client, broker: DeployLogBroker) -> None:
    broker.log("Проверка доступа VPS к api.telegram.org…")
    script = (
        "if curl -fsS --max-time 15 https://api.telegram.org/ >/dev/null 2>&1; then "
        '  echo "Telegram API: доступен с VPS"; '
        "else "
        '  echo "WARN: api.telegram.org недоступен с VPS — укажите proxy в config.json бота"; '
        "fi"
    )
    _run_remote(client, script, broker, ignore_fail=True)


def _verify_bot_health(
    client,
    remote_dir: str,
    container_name: str,
    broker: DeployLogBroker,
) -> None:
    broker.log("Проверка: бот дошёл до polling (не только «Connecting…»)…")
    polling_re = _HEALTH_POLLING_RE
    err_re = _HEALTH_ERR_RE
    script = (
        f"cd {shlex.quote(remote_dir)} && "
        f"{_COMPOSE_DETECT} && "
        f"STATUS=$(docker inspect -f '{{{{.State.Status}}}}' {shlex.quote(container_name)} 2>/dev/null || echo missing) && "
        f"RESTARTS=$(docker inspect -f '{{{{.RestartCount}}}}' {shlex.quote(container_name)} 2>/dev/null || echo 0) && "
        'echo "Статус: $STATUS (restarts: $RESTARTS)" && '
        'if [ "$RESTARTS" -gt 1 ] 2>/dev/null; then '
        '  echo "ERROR: контейнер перезапускается"; '
        "  $COMPOSE logs --tail 80 bot; exit 1; "
        "fi && "
        'if [ "$STATUS" != "running" ]; then '
        "  $COMPOSE logs --tail 80 bot; exit 1; "
        "fi && "
        "WAIT=0 && MAX=90 && "
        "while [ $WAIT -lt $MAX ]; do "
        "  LOGS=\"$($COMPOSE logs bot 2>/dev/null || true)\"; "
        f"  echo \"$LOGS\" | grep -qiE '{err_re}' && "
        '{ echo "ERROR: ошибка в логах контейнера"; echo "$LOGS" | tail -30; exit 1; } || true; '
        f"  if echo \"$LOGS\" | grep -qE '{polling_re}'; then "
        '    echo "$LOGS" | grep -E "Start polling|Run polling|Слушаем Long Poll|Long Poll готов" | tail -1; '
        '    echo "OK: polling активен"; exit 0; '
        "  fi; "
        '  echo "Ждём polling… ${WAIT}s / ${MAX}s"; '
        "  sleep 5; WAIT=$((WAIT+5)); "
        "done && "
        "LOGS=\"$($COMPOSE logs bot 2>/dev/null || true)\" && "
        "echo \"$LOGS\" | tail -40 && "
        'echo "ERROR: бот не дошёл до polling за 90с" && '
        'echo "Причины: api.telegram.org недоступен с VPS (proxy в config.json), конфликт токена, неверный токен" && '
        "exit 1"
    )
    _run_remote(client, script, broker)


def _prepare_remote_data(client, remote_dir: str, broker: DeployLogBroker) -> None:
    """Stop old container, fix legacy file-mount dirs, migrate root → data/."""
    broker.log("Остановка контейнера и очистка legacy-файлов…")
    script = (
        f"cd {shlex.quote(remote_dir)} && "
        f"{_COMPOSE_DETECT} && "
        "$COMPOSE down --remove-orphans 2>/dev/null || true && "
        "mkdir -p data media && "
        "for item in bot.log config.json user_data.db state.json; do "
        '  if [ -d "$item" ]; then echo "FIX: удаляем ошибочную папку $item"; rm -rf "$item"; fi; '
        "done && "
        "for item in user_data.db state.json bot.log; do "
        '  if [ -d "data/$item" ]; then echo "FIX: удаляем ошибочную папку data/$item"; rm -rf "data/$item"; fi; '
        "done && "
        "for f in user_data.db state.json; do "
        '  if [ -f "$f" ] && [ ! -e "data/$f" ]; then echo "MIGRATE: $f → data/$f"; mv "$f" "data/$f"; fi; '
        "done"
    )
    _run_remote(client, script, broker)


def _ensure_remote_data_files(client, remote_dir: str, broker: DeployLogBroker) -> None:
    """Create state.json / user_data.db on server only when still missing after SFTP."""
    broker.log("Проверка data/ (инициализация при первом деплое)…")
    sqlite_cmd = shlex.quote(_INIT_SQLITE_SCRIPT)
    script = (
        f"cd {shlex.quote(remote_dir)} && "
        "[ -f data/state.json ] || echo '{}' > data/state.json && "
        "if [ ! -f data/user_data.db ]; then "
        "  echo 'INIT: создаём data/user_data.db'; "
        f"  docker run --rm -v \"$(pwd)/data:/w\" python:3.12-slim python -c {sqlite_cmd}; "
        "fi && "
        "[ -f config.json ] || (echo 'ERROR: config.json не загружен' && exit 1) && "
        'echo "DATA:" && ls -la data/'
    )
    _run_remote(client, script, broker)


def _docker_compose_up(client, remote_dir: str, broker: DeployLogBroker) -> None:
    compose_script = (
        f"cd {shlex.quote(remote_dir)} && "
        f"{_COMPOSE_DETECT} && "
        "$COMPOSE up -d --build && "
        "$COMPOSE ps && "
        "$COMPOSE logs --tail 40"
    )
    _run_remote(client, compose_script, broker)


def run_ssh_deploy(
    bot_id: int,
    *,
    host: str,
    username: str,
    password: str | None,
    ssh_private_key: str | None,
    port: int,
    broker: DeployLogBroker,
) -> None:
    remote_dir = f"{REMOTE_ROOT}/bot_{bot_id}"
    container_name = f"botbuilder_bot_{bot_id}"
    client = None
    try:
        _stop_local_bot(bot_id, broker)

        broker.log(f"Подключение к {host}:{port} как {username}…")
        client = _connect_ssh(
            host,
            username,
            password=password,
            ssh_private_key=ssh_private_key,
            port=port,
        )
        broker.log("SSH-соединение установлено.")

        broker.log("Шаг 1/5 — Docker + Docker Compose на сервере…")
        _ensure_docker(client, broker)
        _check_telegram_reachability(client, broker)

        broker.log(f"Шаг 2/5 — каталог {remote_dir}…")
        _run_remote(client, f"mkdir -p {shlex.quote(remote_dir)}", broker)

        broker.log("Шаг 3/5 — подготовка data/ на сервере…")
        _prepare_remote_data(client, remote_dir, broker)

        broker.log("Шаг 4/5 — загрузка проекта (SFTP): Dockerfile, compose, bot files…")
        _upload_project(client, bot_id, remote_dir, broker)

        _ensure_remote_data_files(client, remote_dir, broker)

        broker.log("Шаг 5/5 — docker compose up -d --build…")
        _docker_compose_up(client, remote_dir, broker)

        broker.log("Проверка запуска бота…")
        _verify_bot_health(client, remote_dir, container_name, broker)

        broker.log(f"✓ Деплой завершён. Бот #{bot_id} принимает сообщения в Telegram.")
        broker.log("  Можно сразу проверить бота в мессенджере — SSH на сервер не нужен.")
        broker.finish(True)
    except Exception as exc:
        broker.log(f"✗ Ошибка: {exc}")
        broker.finish(False, str(exc))
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def start_ssh_deploy_thread(
    bot_id: int,
    *,
    host: str,
    username: str,
    password: str | None,
    ssh_private_key: str | None,
    port: int,
    broker: DeployLogBroker,
) -> threading.Thread:
    thread = threading.Thread(
        target=run_ssh_deploy,
        kwargs={
            "bot_id": bot_id,
            "host": host,
            "username": username,
            "password": password,
            "ssh_private_key": ssh_private_key,
            "port": port,
            "broker": broker,
        },
        daemon=True,
        name=f"deploy-bot-{bot_id}",
    )
    thread.start()
    return thread
