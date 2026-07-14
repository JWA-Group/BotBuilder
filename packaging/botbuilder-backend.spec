# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — freezes ONLY the BotBuilder FastAPI sidecar.

Output: backend/dist/botbuilder-backend/botbuilder-backend.exe (+ _internal/)
"""
import os
from pathlib import Path

# PyInstaller sets SPECPATH to the *directory* that contains the .spec file
# (not the file path). Prefer that; fall back to process cwd (build script sets repo root).
try:
    ROOT = Path(SPECPATH).resolve().parent
except NameError:
    ROOT = Path(os.getcwd()).resolve()

if not (ROOT / "core" / "main.py").is_file():
    # Safety: if SPECPATH layout differs, use cwd
    cwd_root = Path(os.getcwd()).resolve()
    if (cwd_root / "core" / "main.py").is_file():
        ROOT = cwd_root
    else:
        raise SystemExit(
            f"Cannot locate core/main.py. Tried ROOT={ROOT} and cwd={cwd_root}"
        )

block_cipher = None

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "sqlalchemy.ext.asyncio",
    "aiosqlite",
    "multipart",
    "email_validator",
    "backend.main",
    "backend.db.database",
    "backend.models.user",
    "backend.models.bot",
    "backend.models.command",
    "backend.models.template",
    "backend.routes.auth",
    "backend.routes.bots",
    "backend.routes.commands",
    "backend.routes.bot_runner",
    "backend.routes.scenario",
    "backend.routes.templates",
    "backend.routes.analytics",
    "backend.routes.miniapps",
    "backend.routes.config",
    "backend.routes.plugins",
    "backend.routes.projects",
    "backend.routes.deployment",
    "backend.routes.monitor",
    "backend.routes.inventory",
    "backend.core.inventory_manager",
    "backend.core.bot_runtime_helpers",
    "backend.core.compiler",
    "core.runner",
]


def _is_junk(path_str: str) -> bool:
    """Drop only local project junk — never strip the venv stdlib PyInstaller needs."""
    p = str(path_str).replace("\\", "/").lower()
    # Repo runtime data / history (must not ship inside the freeze)
    if "/projects/" in p or "/.history/" in p:
        return True
    # Explicit project DB/log files only (not python stdlib paths)
    name = p.rsplit("/", 1)[-1]
    if name in ("db.sqlite3", "user_data.db") or name.endswith(".log"):
        return True
    return False


a = Analysis(
    [str(ROOT / "core" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "pytest",
        "pywebview",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

a.datas = [e for e in a.datas if not _is_junk(e[0]) and not _is_junk(e[1])]
a.binaries = [e for e in a.binaries if not _is_junk(e[0]) and not _is_junk(e[1])]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

_icon = ROOT / "BBico.ico"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="botbuilder-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_icon) if _icon.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="botbuilder-backend",
)
