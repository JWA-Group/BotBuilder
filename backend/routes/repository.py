"""Bot-scoped repository filesystem API (tree, read/write, upload, delete, folders)."""

from __future__ import annotations

import base64
import mimetypes
import os
import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.app_paths import PROJECTS_DIR
from backend.core.auth_deps import get_current_user_id_required
from backend.core.bot_access import require_bot_access
from backend.db.database import get_db

router = APIRouter(prefix="/api/repository", tags=["repository"])

MAX_TEXT_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_IMAGE_BYTES = 12 * 1024 * 1024  # 12 MB
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
MAX_TREE_DEPTH = 12
MAX_TREE_ENTRIES = 4000

TEXT_EXTENSIONS = frozenset(
    {
        ".py",
        ".json",
        ".env",
        ".md",
        ".canvas",
        ".txt",
        ".log",
        ".js",
        ".css",
        ".html",
        ".htm",
        ".jinja2",
        ".j2",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".csv",
        ".ini",
        ".conf",
        ".cfg",
        ".sql",
        ".sh",
        ".bat",
        ".ps1",
        ".gitignore",
        ".dockerignore",
    }
)
IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".ico", ".bmp"}
)
# Names treated as text even without extension
TEXT_BASENAMES = frozenset({".env", ".gitignore", "Dockerfile", "Makefile", "LICENSE", "README"})

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._\- ()\[\]]+$")
REL_PATH_RE = re.compile(r"^[A-Za-z0-9._\- /()\[\]]+$")


class FileWriteBody(BaseModel):
    bot_id: int = Field(..., ge=1)
    path: str = Field(..., min_length=1, max_length=512)
    content: str = Field(default="")


class FolderCreateBody(BaseModel):
    bot_id: int = Field(..., ge=1)
    path: str = Field(..., min_length=1, max_length=512)


class FileDeleteBody(BaseModel):
    bot_id: int = Field(..., ge=1)
    path: str = Field(..., min_length=1, max_length=512)


class FileRenameBody(BaseModel):
    bot_id: int = Field(..., ge=1)
    path: str = Field(..., min_length=1, max_length=512)
    new_name: str = Field(..., min_length=1, max_length=255)


class MoveBody(BaseModel):
    bot_id: int = Field(..., ge=1)
    source_path: str = Field(..., min_length=1, max_length=512)
    target_dir: str | None = Field(
        default=None,
        max_length=512,
        description="Destination directory relative to bot root (empty, '/', '.' = root)",
    )
    # Backward-compatible alias
    target_path: str | None = Field(default=None, max_length=512)


class InspectAppBody(BaseModel):
    bot_id: int = Field(..., ge=1)
    path: str = Field(..., min_length=1, max_length=512, description="scripts/<app> relative path")
    write_manifest: bool = True


def _unique_dest(dest_dir: Path, name: str) -> Path:
    """Return dest_dir/name, or dest_dir/stem_N+suffix if name already exists."""
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    i = 1
    while True:
        alt = dest_dir / f"{stem}_{i}{suffix}"
        if not alt.exists():
            return alt
        i += 1


async def _guard(bot_id: int, user_id: int, db: AsyncSession) -> None:
    await require_bot_access(db, bot_id, user_id)


def _bot_root(bot_id: int) -> Path:
    root = (PROJECTS_DIR / f"bot_{bot_id}").resolve()
    if not root.is_dir():
        root.mkdir(parents=True, exist_ok=True)
    return root


def _normalize_rel(path: str | None) -> str:
    raw = (path or "").replace("\\", "/").strip()
    if raw.startswith("/"):
        raw = raw.lstrip("/")
    if not raw or raw in (".", "./", "/"):
        return ""
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == ".." or part.startswith(".."):
            raise HTTPException(status_code=400, detail="Path traversal is not allowed")
        if "\x00" in part:
            raise HTTPException(status_code=400, detail="Invalid path")
        parts.append(part)
    rel = "/".join(parts)
    if rel and not REL_PATH_RE.match(rel):
        raise HTTPException(status_code=400, detail="Invalid path characters")
    return rel


def _normalize_target_folder(path: str | None) -> str:
    """Map '', '/', '.', None → workspace root (empty relative path)."""
    if path is None:
        return ""
    return _normalize_rel(path)


def _resolve_inside(bot_id: int, rel: str) -> tuple[Path, Path]:
    root = _bot_root(bot_id)
    rel_norm = _normalize_rel(rel)
    target = (root / rel_norm).resolve() if rel_norm else root
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path escapes bot workspace") from exc
    return root, target


def _ext_of(name: str) -> str:
    p = Path(name)
    if p.name in TEXT_BASENAMES or p.name.startswith(".env"):
        return p.suffix.lower() or ".env"
    return p.suffix.lower()


def _kind_of(name: str) -> str:
    ext = _ext_of(name)
    base = Path(name).name
    if base in TEXT_BASENAMES or base.startswith(".env"):
        return "text"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in (".log",):
        return "log"
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext in (".db", ".sqlite", ".sqlite3"):
        return "database"
    return "binary"


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _node_meta(path: Path, *, rel: str) -> dict[str, Any]:
    is_dir = path.is_dir()
    size = 0
    if path.is_file():
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
    name = path.name
    kind = "folder" if is_dir else _kind_of(name)
    return {
        "name": name,
        "path": rel.replace("\\", "/"),
        "type": "dir" if is_dir else "file",
        "kind": kind,
        "ext": "" if is_dir else _ext_of(name),
        "size": size,
        "size_label": "" if is_dir else _format_size(size),
    }


def _build_tree(root: Path, *, max_entries: int = MAX_TREE_ENTRIES) -> dict[str, Any]:
    counter = {"n": 0}

    def walk(dir_path: Path, rel: str, depth: int) -> list[dict[str, Any]]:
        if depth > MAX_TREE_DEPTH:
            return []
        children: list[dict[str, Any]] = []
        try:
            entries = sorted(
                dir_path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except OSError:
            return []
        for entry in entries:
            if counter["n"] >= max_entries:
                break
            if entry.name in ("__pycache__", ".git", ".venv", "venv", "node_modules"):
                continue
            if entry.name.endswith(".pyc"):
                continue
            if entry.name.startswith(".") and entry.name not in (
                ".env",
                ".gitignore",
                ".dockerignore",
            ):
                continue
            child_rel = entry.name if not rel else f"{rel}/{entry.name}"
            counter["n"] += 1
            node = _node_meta(entry, rel=child_rel)
            if entry.is_dir():
                node["children"] = walk(entry, child_rel, depth + 1)
            children.append(node)
        return children

    return {
        "bot_id": None,
        "root": str(root),
        "name": root.name,
        "path": "",
        "type": "dir",
        "kind": "folder",
        "children": walk(root, "", 0),
        "truncated": counter["n"] >= max_entries,
        "count": counter["n"],
    }


def _is_text_file(name: str, sample: bytes | None = None) -> bool:
    kind = _kind_of(name)
    if kind in ("text", "log"):
        return True
    if kind == "image":
        return False
    if sample is not None:
        if b"\x00" in sample[:8000]:
            return False
        try:
            sample[:8000].decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False
    return False


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    if len(data) > MAX_TEXT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large for text editor (max {_format_size(MAX_TEXT_BYTES)})",
        )
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _mime_for(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


@router.get("/tree")
async def repository_tree(
    bot_id: int = Query(..., ge=1),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(bot_id, user_id, db)
    root = _bot_root(bot_id)
    tree = _build_tree(root)
    tree["bot_id"] = bot_id
    return tree


@router.get("/file")
async def repository_read_file(
    bot_id: int = Query(..., ge=1),
    path: str = Query(..., min_length=1),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(bot_id, user_id, db)
    _, target = _resolve_inside(bot_id, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")

    rel = _normalize_rel(path)
    kind = _kind_of(target.name)
    size = target.stat().st_size
    meta = {
        "bot_id": bot_id,
        "path": rel,
        "name": target.name,
        "kind": kind,
        "ext": _ext_of(target.name),
        "size": size,
        "size_label": _format_size(size),
        "mime": _mime_for(target),
    }

    if kind == "image":
        if size > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image too large to preview")
        raw = target.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        mime = meta["mime"]
        if target.suffix.lower() == ".svg":
            mime = "image/svg+xml"
        meta["encoding"] = "base64"
        meta["content"] = f"data:{mime};base64,{b64}"
        meta["editable"] = False
        return meta

    sample = target.read_bytes()[:4096] if size else b""
    if not _is_text_file(target.name, sample):
        meta["encoding"] = "binary"
        meta["content"] = None
        meta["editable"] = False
        meta["detail"] = "Binary file — preview not available"
        return meta

    meta["encoding"] = "text"
    meta["content"] = _read_text(target)
    meta["editable"] = True
    if kind == "log" or target.suffix.lower() in (".log", ".txt"):
        meta["kind"] = "log" if target.suffix.lower() == ".log" else kind
    return meta


@router.post("/file")
async def repository_write_file(
    body: FileWriteBody,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(body.bot_id, user_id, db)
    _, target = _resolve_inside(body.bot_id, body.path)
    if target.exists() and target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot write to a directory")
    if not _is_text_file(target.name):
        raise HTTPException(status_code=400, detail="Only text files can be saved via editor")
    content = body.content if body.content is not None else ""
    data = content.encode("utf-8")
    if len(data) > MAX_TEXT_BYTES:
        raise HTTPException(status_code=413, detail="Content too large")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {
        "ok": True,
        "path": _normalize_rel(body.path),
        "size": len(data),
        "size_label": _format_size(len(data)),
    }


@router.post("/upload")
async def repository_upload(
    bot_id: int = Form(...),
    folder: str = Form("assets"),
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(bot_id, user_id, db)
    if bot_id < 1:
        raise HTTPException(status_code=400, detail="Invalid bot_id")
    raw_name = (file.filename or "upload.bin").replace("\\", "/").split("/")[-1]
    if not raw_name or not SAFE_NAME_RE.match(raw_name):
        raise HTTPException(status_code=400, detail="Invalid filename")

    folder_rel = _normalize_rel(folder or "assets") or "assets"
    _, dest_dir = _resolve_inside(bot_id, folder_rel)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / raw_name
    # Avoid overwrite collisions
    if dest.exists():
        stem, suf = dest.stem, dest.suffix
        i = 1
        while dest.exists():
            dest = dest_dir / f"{stem}_{i}{suf}"
            i += 1

    written = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="Upload too large")
                out.write(chunk)
    finally:
        await file.close()

    rel = _normalize_rel(f"{folder_rel}/{dest.name}")
    return {
        "ok": True,
        "path": rel,
        "name": dest.name,
        "size": written,
        "size_label": _format_size(written),
        "kind": _kind_of(dest.name),
    }


@router.delete("/file")
async def repository_delete(
    body: FileDeleteBody,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(body.bot_id, user_id, db)
    root, target = _resolve_inside(body.bot_id, body.path)
    if target == root:
        raise HTTPException(status_code=400, detail="Cannot delete bot root")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    rel = _normalize_rel(body.path)
    if target.is_dir():
        shutil.rmtree(target)
        return {"ok": True, "deleted": rel, "type": "dir"}
    target.unlink()
    return {"ok": True, "deleted": rel, "type": "file"}


@router.post("/folder")
async def repository_create_folder(
    body: FolderCreateBody,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(body.bot_id, user_id, db)
    _, target = _resolve_inside(body.bot_id, body.path)
    if target.exists():
        if target.is_dir():
            return {"ok": True, "path": _normalize_rel(body.path), "existed": True}
        raise HTTPException(status_code=400, detail="A file already exists at this path")
    target.mkdir(parents=True, exist_ok=False)
    return {"ok": True, "path": _normalize_rel(body.path), "existed": False}


@router.post("/rename")
async def repository_rename(
    body: FileRenameBody,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(body.bot_id, user_id, db)
    root, target = _resolve_inside(body.bot_id, body.path)
    if target == root:
        raise HTTPException(status_code=400, detail="Cannot rename bot root")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    new_name = (body.new_name or "").strip().replace("\\", "/").split("/")[-1]
    if not new_name or not SAFE_NAME_RE.match(new_name):
        raise HTTPException(status_code=400, detail="Invalid new name")
    dest = target.parent / new_name
    if dest.exists():
        raise HTTPException(status_code=409, detail="Target name already exists")
    try:
        dest.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid destination") from exc
    target.rename(dest)
    new_rel = str(dest.relative_to(root)).replace("\\", "/")
    return {"ok": True, "path": new_rel, "name": new_name}


@router.post("/move")
async def repository_move(
    body: MoveBody,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Move a file or folder into target_dir inside the bot workspace.

    target_dir of "", "/", ".", or None means the bot workspace root.
    Name collisions get an automatic numeric suffix (file → file_1).
    Circular moves (folder into itself / descendant) return HTTP 400.
    Same-folder moves are a graceful no-op.
    """
    await _guard(body.bot_id, user_id, db)
    root = _bot_root(body.bot_id)

    source_rel = _normalize_rel(body.source_path)
    if not source_rel:
        raise HTTPException(status_code=400, detail="Cannot move bot root")
    source = (root / source_rel).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Source escapes workspace") from exc
    if not source.exists():
        raise HTTPException(status_code=404, detail="Source not found")

    raw_target = body.target_dir if body.target_dir is not None else body.target_path
    target_folder_rel = _normalize_target_folder(raw_target)
    dest_dir = (root / target_folder_rel).resolve() if target_folder_rel else root.resolve()
    try:
        dest_dir.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Target escapes workspace") from exc

    if dest_dir != root and not dest_dir.exists():
        dest_dir.mkdir(parents=True, exist_ok=True)
    if not dest_dir.is_dir():
        raise HTTPException(status_code=400, detail="Target path is not a directory")

    # Circular move guard: target identical to source OR target inside source
    source_res = source.resolve()
    dest_res = dest_dir.resolve()
    if source_res == dest_res:
        raise HTTPException(
            status_code=400, detail="Cannot move a folder into itself"
        )
    if source.is_dir():
        try:
            dest_res.relative_to(source_res)
            raise HTTPException(
                status_code=400,
                detail="Cannot move a folder into itself or a subfolder",
            )
        except ValueError:
            pass
        except HTTPException:
            raise

    # Same parent → no-op
    if source.parent.resolve() == dest_res:
        tree = _build_tree(root)
        tree["bot_id"] = body.bot_id
        return {
            "ok": True,
            "path": source_rel,
            "name": source.name,
            "moved": False,
            "source_path": source_rel,
            "target_dir": target_folder_rel,
            "tree": tree,
        }

    dest = _unique_dest(dest_dir, source.name).resolve()
    try:
        dest.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Destination escapes workspace") from exc

    shutil.move(str(source), str(dest))
    new_rel = str(dest.relative_to(root)).replace("\\", "/")
    tree = _build_tree(root)
    tree["bot_id"] = body.bot_id
    return {
        "ok": True,
        "path": new_rel,
        "name": dest.name,
        "moved": True,
        "source_path": source_rel,
        "target_dir": target_folder_rel,
        "tree": tree,
    }


@router.post("/inspect-app")
async def repository_inspect_app(
    body: InspectAppBody,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """AST-inspect a standalone app under scripts/ and ensure manifest.json."""
    from backend.services.app_inspector import (
        AppInspectorError,
        analyze_standalone_app,
        resolve_app_dir,
    )

    await _guard(body.bot_id, user_id, db)
    root = _bot_root(body.bot_id)
    try:
        app_dir = resolve_app_dir(root, body.path)
        analysis = analyze_standalone_app(app_dir, write_manifest=bool(body.write_manifest))
    except AppInspectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Inspect failed: {exc}") from exc

    # Drop absolute paths from API response
    safe = {
        "ok": True,
        "bot_id": body.bot_id,
        "app_folder_path": str(app_dir.relative_to(root)).replace("\\", "/"),
        "app_name": analysis.get("app_name"),
        "description": analysis.get("description"),
        "entrypoint": analysis.get("entrypoint"),
        "functions_count": analysis.get("functions_count"),
        "dependencies": analysis.get("dependencies"),
        "http_clients": analysis.get("http_clients"),
        "manifest": analysis.get("manifest"),
        "manifest_source": analysis.get("manifest_source"),
        "files": [
            {
                "path": f.get("path"),
                "functions": [
                    {
                        "name": fn.get("name"),
                        "async": fn.get("async"),
                        "args": fn.get("args"),
                        "returns": fn.get("returns"),
                    }
                    for fn in (f.get("functions") or [])
                ],
                "error": f.get("error"),
            }
            for f in (analysis.get("files") or [])
        ],
    }
    return safe
