"""
Десктоп-лаунчер BotBuilder для Windows.
Запускает uvicorn в фоне и открывает окно приложения (WebView2 через pywebview).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = 8000
APP_URL = f"http://{HOST}:{PORT}/"
HEALTH_URL = f"http://{HOST}:{PORT}/api/health"


def _python_exe() -> Path:
    venv_py = ROOT / "venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return venv_py
    return Path(sys.executable)


def _port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((HOST, PORT)) == 0


def _wait_for_server(timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.15)
    return False


def _server_supports_plugin_builder() -> bool:
    """POST create-custom: 422/400 = маршрут есть; 405 = старый backend."""
    url = f"http://{HOST}:{PORT}/api/plugins/create-custom"
    try:
        req = urllib.request.Request(
            url,
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status < 500
    except urllib.error.HTTPError as exc:
        return exc.code in (400, 422)
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _start_server() -> subprocess.Popen | None:
    if _port_in_use():
        if not _server_supports_plugin_builder():
            print(
                f"\nНа порту {PORT} уже запущен старый сервер без «Мастера компонентов».\n"
                "Закройте все окна BotBuilder / остановите uvicorn и запустите приложение снова.\n"
                "Или в диспетчере задач завершите процесс python.exe с uvicorn на порту 8000.\n"
            )
        return None

    env = os.environ.copy()
    env["DESKTOP_APP"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [
        str(_python_exe()),
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        HOST,
        "--port",
        str(PORT),
        "--log-level",
        "warning",
    ]
    return subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _open_webview(url: str) -> None:
    import webview

    webview.create_window(
        "BotBuilder",
        url,
        width=1280,
        height=840,
        min_size=(900, 600),
        text_select=True,
    )
    webview.start()


def _open_browser_app(url: str) -> None:
    for browser in (
        ["msedge", f"--app={url}"],
        ["chrome", f"--app={url}"],
    ):
        try:
            subprocess.Popen(browser)
            return
        except OSError:
            continue
    import webbrowser

    webbrowser.open(url)


def main() -> int:
    if sys.platform != "win32":
        print("Десктоп-лаунчер рассчитан на Windows. Используйте run.bat.")
        return 1

    server = _start_server()
    if server is not None and not _wait_for_server():
        server.terminate()
        print("Не удалось запустить сервер. Проверьте venv и зависимости (run install-desktop.bat).")
        return 1

    if server is None and not _wait_for_server(timeout=5):
        print(f"Сервер не отвечает на {APP_URL}. Запустите run.bat или перезапустите BotBuilder.")
        return 1

    try:
        try:
            _open_webview(APP_URL)
        except ImportError:
            print("pywebview не установлен — открываю в режиме приложения браузера.")
            _open_browser_app(APP_URL)
            if server is not None:
                input("Нажмите Enter, чтобы остановить сервер...")
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
