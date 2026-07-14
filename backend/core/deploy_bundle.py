"""Production Docker bundle generation and ZIP export for bot projects."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from backend.utils.generate_main import BASE_DIR, generate_main_from_scenario, get_bot_platform

PROJECTS_DIR = Path(BASE_DIR)

# Never overwrite on server when redeploying (SSH upload skips if remote file exists).
PERSISTENT_REMOTE_FILES = frozenset({"user_data.db", "state.json"})


def bot_project_dir(bot_id: int) -> Path:
    return PROJECTS_DIR / f"bot_{bot_id}"


def read_bot_proxy(bot_id: int) -> str | None:
    path = bot_project_dir(bot_id) / "config.json"
    if not path.is_file():
        return None
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for key in ("proxy", "https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        val = (cfg.get(key) or "").strip()
        if val:
            return val
    return None


def render_requirements_txt(platform: str) -> str:
    _ = platform
    lines = [
        "aiogram==3.4.1",
        "pydantic>=2.4.1,<2.10",
        "aiohttp>=3.9.0,<4",
    ]
    return "\n".join(lines) + "\n"


def render_dockerfile(platform: str = "telegram") -> str:
    _ = platform
    return "\n".join(
        [
            "FROM python:3.12-slim",
            "WORKDIR /app",
            "ENV PYTHONUNBUFFERED=1",
            "ENV BOT_DATA_DIR=/app/data",
            "ENV BOTBUILDER_DOCKER=1",
            "RUN apt-get update \\",
            "    && apt-get install -y --no-install-recommends ca-certificates \\",
            "    && rm -rf /var/lib/apt/lists/*",
            "RUN mkdir -p /app/data /app/media",
            "COPY requirements.txt .",
            "RUN pip install --no-cache-dir -r requirements.txt",
            "COPY . .",
            'CMD ["python", "-u", "main.py"]',
            "",
        ]
    )


def render_docker_compose(bot_id: int, service_name: str = "bot") -> str:
    container = f"botbuilder_bot_{bot_id}"
    env_lines = [
        "    environment:",
        "      BOT_DATA_DIR: /app/data",
        '      BOTBUILDER_DOCKER: "1"',
    ]
    proxy = read_bot_proxy(bot_id)
    if proxy:
        escaped = proxy.replace("\\", "\\\\").replace('"', '\\"')
        env_lines.append(f'      HTTPS_PROXY: "{escaped}"')
        env_lines.append(f'      HTTP_PROXY: "{escaped}"')
    return "\n".join(
        [
            "services:",
            f"  {service_name}:",
            "    build: .",
            f"    container_name: {container}",
            "    restart: always",
            *env_lines,
            "    volumes:",
            "      - ./data:/app/data",
            "      - ./media:/app/media",
            "",
        ]
    )


def render_dockerignore() -> str:
    return "\n".join(
        [
            "venv/",
            ".venv/",
            "__pycache__/",
            "*.pyc",
            ".git/",
            "data/",
            "bot.log",
            "launcher.log",
            "stderr.log",
            "run.pid",
            "",
        ]
    )


def render_env_example() -> str:
    return "\n".join(
        [
            "# Токен можно задать здесь или в config.json",
            "BOT_API_TOKEN=",
            "",
        ]
    )


def render_readme(bot_id: int, platform: str) -> str:
    return "\n".join(
        [
            f"# BotBuilder export — bot_{bot_id}",
            "",
            "## Docker",
            "```bash",
            "mkdir -p data media",
            "docker compose up -d --build",
            "docker compose logs -f",
            "docker compose ps",
            "```",
            "",
            "Persistent data: `./data` (user_data.db, state.json, bot.log)",
            "",
            f"Platform: **{platform}**",
            "",
        ]
    )


def collect_project_files(bot_id: int) -> dict[str, bytes | str]:
    """Return relative path -> content for deployment bundle."""
    root = bot_project_dir(bot_id)
    if not root.is_dir():
        raise FileNotFoundError(f"Project bot_{bot_id} not found")

    platform = get_bot_platform(bot_id)
    files: dict[str, bytes | str] = {
        "requirements.txt": render_requirements_txt(platform),
        "Dockerfile": render_dockerfile(platform),
        "docker-compose.yml": render_docker_compose(bot_id),
        ".dockerignore": render_dockerignore(),
        ".env.example": render_env_example(),
        "README-DEPLOY.md": render_readme(bot_id, platform),
    }

    include_names = {
        "main.py",
        "config.json",
        "scenario.json",
        "state.json",
        "user_data.db",
        "handlers.json",
        "keyboard.json",
        "fsm.json",
        "miniapp.json",
    }

    for name in include_names:
        path = root / name
        if path.is_file():
            files[name] = path.read_bytes()

    if "state.json" not in files:
        files["state.json"] = b"{}"

    media_dir = root / "media"
    if media_dir.is_dir():
        for item in media_dir.rglob("*"):
            if item.is_file():
                rel = "media/" + item.relative_to(media_dir).as_posix()
                files[rel] = item.read_bytes()

    return files


def build_export_zip(bot_id: int, *, compile_first: bool = True) -> bytes:
    """Compile bot (optional) and pack production-ready archive."""
    if compile_first:
        generate_main_from_scenario(bot_id)

    files = collect_project_files(bot_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest: dict[str, Any] = {
            "format_version": 1,
            "bot_id": bot_id,
            "platform": get_bot_platform(bot_id),
            "files": sorted(files.keys()),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for rel, content in files.items():
            if isinstance(content, str):
                zf.writestr(rel, content)
            else:
                zf.writestr(rel, content)
    return buf.getvalue()


def write_bundle_to_directory(bot_id: int, target_dir: Path, *, compile_first: bool = True) -> None:
    """Write deployment files to *target_dir* (used by SSH deploy)."""
    if compile_first:
        generate_main_from_scenario(bot_id)

    target_dir.mkdir(parents=True, exist_ok=True)
    files = collect_project_files(bot_id)
    for rel, content in files.items():
        dest = target_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            dest.write_text(content, encoding="utf-8")
        else:
            dest.write_bytes(content)
