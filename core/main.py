"""
BotBuilder FastAPI sidecar entry point for the Electron desktop shell.

Usage:
    python core/main.py --port 8000
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="BotBuilder API sidecar")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    args = parser.parse_args()

    os.environ.setdefault("DESKTOP_APP", "1")
    os.environ["APP_BASE_URL"] = f"http://{args.host}:{args.port}"
    os.environ["PYTHONUNBUFFERED"] = "1"

    # Writable user data (Electron sets BOTBUILDER_DATA_DIR); create blank folders.
    from backend.core.app_paths import ensure_data_dirs, get_app_root

    if not os.environ.get("BOTBUILDER_APP_ROOT"):
        os.environ["BOTBUILDER_APP_ROOT"] = str(get_app_root())
    data_dir = ensure_data_dirs()
    os.environ.setdefault("BOTBUILDER_DATA_DIR", str(data_dir))

    if sys.platform == "win32":
        import asyncio

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    import uvicorn

    # When frozen, load the ASGI app object directly (no string import reload issues).
    if getattr(sys, "frozen", False):
        from backend.main import app as asgi_app

        uvicorn.run(
            asgi_app,
            host=args.host,
            port=args.port,
            log_level="warning",
        )
    else:
        uvicorn.run(
            "backend.main:app",
            host=args.host,
            port=args.port,
            log_level="warning",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
