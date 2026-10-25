"""AST inspector for standalone Python apps under bot scripts/ folders.

Discovers entrypoints, args, type hints, docstrings, HTTP deps, and synthesizes
manifest.json when missing.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

HTTP_MODULES = frozenset(
    {
        "httpx",
        "aiohttp",
        "requests",
        "urllib",
        "urllib.request",
        "urllib3",
        "http.client",
    }
)

ENTRY_CANDIDATES = (
    "main",
    "run",
    "handler",
    "handle",
    "execute",
    "process",
    "app",
    "start",
)

ENTRY_FILES = ("main.py", "app.py", "handler.py", "run.py", "__init__.py")


class AppInspectorError(ValueError):
    """Invalid app path or unreadable Python sources."""


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def _ann_to_str(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Constant):
            return str(node.value)
        return ""


def _docstring(node: ast.AST) -> str:
    try:
        doc = ast.get_docstring(node) or ""
    except TypeError:
        doc = ""
    return re.sub(r"\s+", " ", doc).strip()[:500]


def _arg_info(args: ast.arguments) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    positional = list(args.posonlyargs) + list(args.args)
    defaults = list(args.defaults or [])
    # Align defaults to the end of positional
    default_offset = len(positional) - len(defaults)
    for i, arg in enumerate(positional):
        name = arg.arg
        if name in ("self", "cls"):
            continue
        has_default = i >= default_offset
        default_val = None
        if has_default:
            dnode = defaults[i - default_offset]
            try:
                default_val = ast.literal_eval(dnode)
            except Exception:
                try:
                    default_val = ast.unparse(dnode)
                except Exception:
                    default_val = None
        out.append(
            {
                "name": name,
                "type": _ann_to_str(arg.annotation) or "Any",
                "required": not has_default,
                "default": default_val,
            }
        )
    for arg in args.kwonlyargs:
        out.append(
            {
                "name": arg.arg,
                "type": _ann_to_str(arg.annotation) or "Any",
                "required": arg.arg not in {a.arg for a in args.kwonlyargs if False},
                "default": None,
            }
        )
    # Fix kwonly required using kw_defaults
    for i, arg in enumerate(args.kwonlyargs):
        for item in out:
            if item["name"] == arg.arg:
                item["required"] = args.kw_defaults[i] is None
                if args.kw_defaults[i] is not None:
                    try:
                        item["default"] = ast.literal_eval(args.kw_defaults[i])
                    except Exception:
                        try:
                            item["default"] = ast.unparse(args.kw_defaults[i])
                        except Exception:
                            pass
                break
    return out


def _collect_imports(tree: ast.AST) -> list[str]:
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.append(node.module.split(".")[0])
    # preserve order, unique
    seen: set[str] = set()
    ordered: list[str] = []
    for m in mods:
        if m not in seen:
            seen.add(m)
            ordered.append(m)
    return ordered


def _analyze_file(path: Path, root: Path) -> dict[str, Any]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AppInspectorError(f"Cannot read {path.name}: {exc}") from exc
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return {
            "path": _safe_rel(path, root),
            "error": f"syntax_error: {exc.msg}",
            "functions": [],
            "imports": [],
            "http_clients": [],
        }

    functions: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                    "args": _arg_info(node.args),
                    "returns": _ann_to_str(node.returns) or "Any",
                    "docstring": _docstring(node),
                    "lineno": getattr(node, "lineno", 0),
                }
            )
    imports = _collect_imports(tree)
    http_clients = [m for m in imports if m in HTTP_MODULES or any(m.startswith(h) for h in HTTP_MODULES)]
    return {
        "path": _safe_rel(path, root),
        "functions": functions,
        "imports": imports,
        "http_clients": http_clients,
        "module_doc": _docstring(tree),
    }


def _pick_entrypoint(files: list[dict[str, Any]]) -> dict[str, Any] | None:
    # Prefer named entry files + common function names
    by_path = {f["path"]: f for f in files if not f.get("error")}
    for fname in ENTRY_FILES:
        for path, meta in by_path.items():
            if path.endswith(fname) or Path(path).name == fname:
                funcs = meta.get("functions") or []
                for cand in ENTRY_CANDIDATES:
                    for fn in funcs:
                        if fn.get("name") == cand:
                            return {
                                "file": path,
                                "function": cand,
                                "async": bool(fn.get("async")),
                                "args": fn.get("args") or [],
                                "returns": fn.get("returns") or "Any",
                                "docstring": fn.get("docstring") or "",
                            }
                if funcs:
                    fn = funcs[0]
                    return {
                        "file": path,
                        "function": fn.get("name"),
                        "async": bool(fn.get("async")),
                        "args": fn.get("args") or [],
                        "returns": fn.get("returns") or "Any",
                        "docstring": fn.get("docstring") or "",
                    }
    # Global scan by candidate names
    for cand in ENTRY_CANDIDATES:
        for meta in by_path.values():
            for fn in meta.get("functions") or []:
                if fn.get("name") == cand:
                    return {
                        "file": meta["path"],
                        "function": cand,
                        "async": bool(fn.get("async")),
                        "args": fn.get("args") or [],
                        "returns": fn.get("returns") or "Any",
                        "docstring": fn.get("docstring") or "",
                    }
    # First function anywhere
    for meta in by_path.values():
        funcs = meta.get("functions") or []
        if funcs:
            fn = funcs[0]
            return {
                "file": meta["path"],
                "function": fn.get("name"),
                "async": bool(fn.get("async")),
                "args": fn.get("args") or [],
                "returns": fn.get("returns") or "Any",
                "docstring": fn.get("docstring") or "",
            }
    return None


def _guess_mustache(arg_name: str) -> str:
    n = (arg_name or "").strip().lower()
    aliases = {
        "user_id": "{{user.telegram_id}}",
        "telegram_id": "{{user.telegram_id}}",
        "tg_id": "{{user.telegram_id}}",
        "chat_id": "{{user.chat_id}}",
        "username": "{{user.tg_user_name}}",
        "user_name": "{{user.tg_user_name}}",
        "name": "{{user.name}}",
        "phone": "{{user.phone}}",
        "email": "{{user.email}}",
        "city": "{{user.city}}",
    }
    if n in aliases:
        return aliases[n]
    return "{{user." + re.sub(r"[^a-z0-9_]", "_", n) + "}}"


def synthesize_manifest(
    analysis: dict[str, Any],
    *,
    app_name: str | None = None,
) -> dict[str, Any]:
    """Build a valid manifest.json from AST analysis."""
    entry = analysis.get("entrypoint") or {}
    args = entry.get("args") if isinstance(entry.get("args"), list) else []
    inputs: list[dict[str, Any]] = []
    for a in args:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "").strip()
        if not name or name in ("bot", "ctx", "message", "state"):
            continue
        inputs.append(
            {
                "name": name,
                "type": str(a.get("type") or "Any"),
                "required": bool(a.get("required", True)),
                "source": _guess_mustache(name),
                "description": "",
            }
        )

    http = analysis.get("http_clients") or []
    deps = analysis.get("dependencies") or []
    name = app_name or analysis.get("app_name") or "standalone_app"
    entry_file = str(entry.get("file") or "main.py")
    entry_fn = str(entry.get("function") or "main")

    return {
        "name": name,
        "version": "1.0.0",
        "description": str(analysis.get("description") or entry.get("docstring") or name),
        "entrypoint": {
            "file": entry_file,
            "function": entry_fn,
            "async": bool(entry.get("async")),
        },
        "inputs": inputs,
        "outputs": [
            {"name": "result", "type": "Any", "description": "Primary return payload"},
            {"name": "error", "type": "string", "description": "Error message when failed"},
        ],
        "ports": [
            {"id": "success", "index": 0, "label": "Success"},
            {"id": "error", "index": 1, "label": "Error"},
        ],
        "dependencies": sorted(set(list(deps) + list(http))),
        "http_clients": list(http),
    }


def analyze_standalone_app(app_dir_path: str | Path, *, write_manifest: bool = True) -> dict[str, Any]:
    """
    Scan a standalone app folder, parse AST, and optionally write manifest.json.

    Returns analysis dict including ``manifest`` and ``manifest_path``.
    """
    root = Path(app_dir_path).expanduser().resolve()
    if not root.exists():
        raise AppInspectorError(f"App directory not found: {root}")
    if not root.is_dir():
        raise AppInspectorError(f"Not a directory: {root}")

    py_files = sorted(
        p for p in root.rglob("*.py") if p.is_file() and "__pycache__" not in p.parts
    )
    if not py_files:
        raise AppInspectorError(f"No Python files in {root}")

    file_reports: list[dict[str, Any]] = []
    all_imports: list[str] = []
    http_clients: list[str] = []
    for path in py_files:
        report = _analyze_file(path, root)
        file_reports.append(report)
        for m in report.get("imports") or []:
            if m not in all_imports:
                all_imports.append(m)
        for m in report.get("http_clients") or []:
            if m not in http_clients:
                http_clients.append(m)

    entrypoint = _pick_entrypoint(file_reports)
    app_name = root.name
    description = ""
    for fr in file_reports:
        if fr.get("module_doc"):
            description = fr["module_doc"]
            break
    if not description and entrypoint:
        description = str(entrypoint.get("docstring") or "")

    analysis: dict[str, Any] = {
        "ok": True,
        "app_dir": str(root),
        "app_name": app_name,
        "description": description,
        "files": file_reports,
        "entrypoint": entrypoint,
        "dependencies": all_imports,
        "http_clients": http_clients,
        "functions_count": sum(len(f.get("functions") or []) for f in file_reports),
    }

    manifest_path = root / "manifest.json"
    existing: dict[str, Any] | None = None
    if manifest_path.is_file():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = None

    if isinstance(existing, dict) and existing.get("entrypoint"):
        manifest = existing
        analysis["manifest_source"] = "existing"
    else:
        manifest = synthesize_manifest(analysis, app_name=app_name)
        analysis["manifest_source"] = "synthesized"
        if write_manifest:
            try:
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                raise AppInspectorError(f"Cannot write manifest.json: {exc}") from exc

    analysis["manifest"] = manifest
    analysis["manifest_path"] = str(manifest_path)
    return analysis


def resolve_app_dir(bot_root: str | Path, app_folder_path: str) -> Path:
    """Resolve app_folder_path relative to bot root (e.g. scripts/my_parser)."""
    root = Path(bot_root).resolve()
    raw = (app_folder_path or "").replace("\\", "/").strip().lstrip("/")
    if not raw:
        raise AppInspectorError("app_folder_path is required")
    if ".." in raw.split("/"):
        raise AppInspectorError("Path traversal is not allowed")
    # Allow bare name → scripts/<name>
    if "/" not in raw:
        raw = f"scripts/{raw}"
    if not raw.startswith("scripts/"):
        raw = f"scripts/{raw}"
    target = (root / raw).resolve()
    if root not in target.parents and target != root:
        raise AppInspectorError("App path escapes bot root")
    return target


def write_standalone_app(
    bot_root: str | Path,
    *,
    app_name: str,
    python_files: dict[str, str],
    manifest: dict[str, Any] | None = None,
    description: str = "",
) -> dict[str, Any]:
    """
    Create scripts/<app_name>/ with provided .py sources and manifest.

    ``python_files`` maps relative filenames → source code.
    """
    slug = re.sub(r"[^a-z0-9_-]", "_", (app_name or "custom_app").strip().lower())
    if not slug:
        slug = "custom_app"
    root = Path(bot_root).resolve()
    app_dir = root / "scripts" / slug
    app_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for rel, code in (python_files or {}).items():
        name = Path(str(rel).replace("\\", "/")).name
        if not name.endswith(".py"):
            name = f"{name}.py"
        if name.startswith(".") or ".." in name:
            continue
        path = app_dir / name
        path.write_text(str(code or ""), encoding="utf-8")
        written.append(name)

    if not written:
        # Minimal stub
        stub = (
            '"""Standalone app generated by BotCopilot."""\n\n'
            "async def main(**kwargs):\n"
            '    """Entrypoint. Return dict with ok=True/False."""\n'
            "    return {\"ok\": True, \"result\": kwargs}\n"
        )
        (app_dir / "main.py").write_text(stub, encoding="utf-8")
        written.append("main.py")

    analysis = analyze_standalone_app(app_dir, write_manifest=False)
    if isinstance(manifest, dict) and manifest:
        # Merge AI-provided manifest over synthesized
        base = synthesize_manifest(analysis, app_name=slug)
        merged = {**base, **manifest}
        if description:
            merged["description"] = description
        merged.setdefault("name", slug)
        (app_dir / "manifest.json").write_text(
            json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        analysis["manifest"] = merged
        analysis["manifest_source"] = "provided"
    else:
        analysis = analyze_standalone_app(app_dir, write_manifest=True)

    analysis["written_files"] = written
    analysis["app_folder_path"] = f"scripts/{slug}"
    return analysis


def build_bridge_node_data(analysis: dict[str, Any], *, app_folder_path: str | None = None) -> dict[str, Any]:
    """Map inspector result → app_bridge block.data for the canvas."""
    manifest = analysis.get("manifest") if isinstance(analysis.get("manifest"), dict) else {}
    entry = manifest.get("entrypoint") if isinstance(manifest.get("entrypoint"), dict) else {}
    inputs = manifest.get("inputs") if isinstance(manifest.get("inputs"), list) else []
    input_map: dict[str, str] = {}
    for item in inputs:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        source = str(item.get("source") or _guess_mustache(name))
        input_map[name] = source

    folder = app_folder_path or analysis.get("app_folder_path") or f"scripts/{analysis.get('app_name') or 'app'}"
    return {
        "appName": str(manifest.get("name") or analysis.get("app_name") or "App"),
        "appFolder": folder.replace("\\", "/"),
        "entryFile": str(entry.get("file") or "main.py"),
        "entryFunction": str(entry.get("function") or "main"),
        "entryAsync": bool(entry.get("async")),
        "inputMap": input_map,
        "description": str(manifest.get("description") or analysis.get("description") or ""),
        "dependencies": list(manifest.get("dependencies") or analysis.get("dependencies") or []),
    }
