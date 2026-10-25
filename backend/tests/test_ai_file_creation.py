#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Diagnostic Test Suite — AI Copilot physical file creation pipeline.

Run from repo root:
  python backend/tests/test_ai_file_creation.py

Prints clean [PASS] / [FAIL] / [SKIP] lines for each stage.
Zero emojis.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

# Ensure repo root is on sys.path when executed as a script
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _ok(msg: str) -> None:
    print(f"[PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def _info(msg: str) -> None:
    print(f"[INFO] {msg}")


def _skip(msg: str) -> None:
    print(f"[SKIP] {msg}")


def test_1_direct_disk_io() -> bool:
    print("\n=== Test 1: Direct Disk IO ===")
    from backend.services.ai_tools import get_bot_workspace_dir, write_workspace_file

    bot_id = 990098
    rel = "scripts/test_script/app.py"
    content = "# test\n"
    try:
        result = write_workspace_file(
            bot_id=bot_id,
            relative_path=rel,
            content=content,
        )
        if not (result.get("ok") or result.get("success")):
            _fail(f"File system permission error. detail={result.get('error')}")
            return False
        workspace = get_bot_workspace_dir(bot_id)
        target = workspace / rel
        if not target.is_file():
            _fail(f"File system permission error. missing path={target}")
            return False
        text = target.read_text(encoding="utf-8")
        if "# test" not in text:
            _fail("File system permission error. content mismatch.")
            return False
        _ok("Direct file system writing works.")
        _info(f"path={target}")
        return True
    except Exception as exc:
        _fail(f"File system permission error. Exception: {exc}")
        traceback.print_exc()
        return False
    finally:
        # Cleanup test folder under bot_990098
        try:
            workspace = get_bot_workspace_dir(bot_id)
            victim = workspace / "scripts" / "test_script"
            if victim.is_dir():
                shutil.rmtree(victim, ignore_errors=True)
        except Exception:
            pass


def test_2_tool_schema() -> bool:
    print("\n=== Test 2: Tool Registry Schema Verification ===")
    try:
        from backend.routes.ai_assistant import BOTCOPILOT_TOOLS
    except Exception as exc:
        _fail(f"Malformed tool definition. Cannot import BOTCOPILOT_TOOLS: {exc}")
        return False

    found = None
    for item in BOTCOPILOT_TOOLS or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "function":
            continue
        fn = item.get("function")
        if not isinstance(fn, dict):
            continue
        if fn.get("name") == "write_workspace_file":
            found = item
            break

    if not found:
        _fail("Malformed tool definition. write_workspace_file not registered.")
        return False

    fn = found["function"]
    params = fn.get("parameters")
    if not isinstance(params, dict):
        _fail("Malformed tool definition. parameters missing.")
        return False
    props = params.get("properties") or {}
    required = params.get("required") or []
    if "relative_path" not in props or "content" not in props:
        _fail("Malformed tool definition. relative_path/content missing in properties.")
        return False
    if "relative_path" not in required or "content" not in required:
        _fail("Malformed tool definition. relative_path/content not required.")
        return False
    if not isinstance(fn.get("description"), str) or not fn.get("description"):
        _fail("Malformed tool definition. description missing.")
        return False

    # Shape check: OpenAI/DeepSeek function format
    shape_ok = (
        found.get("type") == "function"
        and isinstance(found.get("function"), dict)
        and found["function"].get("name") == "write_workspace_file"
    )
    if not shape_ok:
        _fail("Malformed tool definition.")
        return False

    _ok("Tool schema valid.")
    _info(json.dumps({"name": fn["name"], "required": required}, ensure_ascii=False))
    return True


def test_3_tool_dispatch() -> bool:
    print("\n=== Test 3: Tool Dispatch Execution ===")
    from backend.services.ai_tools import execute_tool_call, get_bot_workspace_dir

    bot_id = 990098
    rel = "scripts/dispatch_check/app.py"
    payload = {
        "id": "call_diag_1",
        "type": "function",
        "function": {
            "name": "write_workspace_file",
            "arguments": json.dumps(
                {
                    "relative_path": rel,
                    "content": "print('dispatch_ok')\n",
                    "bot_id": bot_id,
                },
                ensure_ascii=False,
            ),
        },
    }
    try:
        result = execute_tool_call(payload, bot_id=bot_id)
        success = bool(result.get("success") or result.get("ok"))
        path = result.get("path") or result.get("relative_path")
        if not success or not path:
            _fail(f"Dispatch failed. result={result}")
            return False
        workspace = get_bot_workspace_dir(bot_id)
        if not (workspace / rel).is_file():
            _fail(f"Dispatch reported success but file missing: {workspace / rel}")
            return False
        _ok("Tool dispatch execution works.")
        _info(f"success=true path={path}")
        return True
    except Exception as exc:
        _fail(f"Dispatch exception: {exc}")
        traceback.print_exc()
        return False
    finally:
        try:
            workspace = get_bot_workspace_dir(bot_id)
            victim = workspace / "scripts" / "dispatch_check"
            if victim.is_dir():
                shutil.rmtree(victim, ignore_errors=True)
        except Exception:
            pass


def test_4_live_llm() -> bool:
    print("\n=== Test 4: Live LLM Tool Call Invocation ===")
    try:
        from backend.core.ai_config import load_ai_config
        from backend.routes.ai_assistant import BOTCOPILOT_TOOLS
        from backend.services.ai_provider import AIProvider
        from backend.services.ai_tools import execute_tool_call, get_bot_workspace_dir
        from backend.services.ai_intent import (
            WORKSPACE_FILE_CRITICAL_DIRECTIVE,
            maybe_autosave_code_blocks,
        )
    except Exception as exc:
        _fail(f"Cannot import AI stack: {exc}")
        return False

    cfg = load_ai_config()
    if not cfg.api_key:
        _skip("Live LLM skipped — AI API key not configured.")
        return True
    if not cfg.enabled:
        _skip("Live LLM skipped — AI disabled in settings.")
        return True

    bot_id = 990098
    prompt = (
        "Create a test script at scripts/diag_test/app.py containing print('ok'). "
        "You MUST call write_workspace_file. Do not only reply with markdown."
    )
    system = (
        "You are a tool-calling agent. "
        + WORKSPACE_FILE_CRITICAL_DIRECTIVE
        + " Reply in one short sentence after tools."
    )

    async def _run() -> tuple[str, list]:
        provider = AIProvider(cfg)

        async def executor(name: str, args: dict):
            return execute_tool_call(
                name=name,
                arguments=args,
                bot_id=bot_id,
            )

        return await provider.run_tool_loop(
            [{"role": "user", "content": prompt}],
            system,
            BOTCOPILOT_TOOLS,
            executor,
            max_rounds=3,
            temperature=0.1,
            purpose="diag-file-creation",
            bot_id=bot_id,
            model=cfg.model_for_role("planner") if hasattr(cfg, "model_for_role") else cfg.model,
        )

    try:
        reply, executed = asyncio.run(_run())
    except Exception as exc:
        _fail(f"Live LLM call failed: {exc}")
        traceback.print_exc()
        return False

    tool_names = [e.get("name") for e in executed if isinstance(e, dict)]
    wrote = "write_workspace_file" in tool_names
    workspace = get_bot_workspace_dir(bot_id)
    target = workspace / "scripts" / "diag_test" / "app.py"

    if wrote and target.is_file():
        _ok("Live LLM triggered write_workspace_file and file exists.")
        _info(f"tools={tool_names} path={target}")
        ok = True
    elif wrote:
        _fail("LLM called write_workspace_file but file not found on disk.")
        ok = False
    else:
        _info("LLM returned text-only; attempting markdown fallback autosave.")
        saved = maybe_autosave_code_blocks(
            bot_id=bot_id,
            user_text=prompt,
            reply=reply or "",
            already_wrote=False,
        )
        if saved and target.is_file():
            _ok("Live LLM text-only, but fallback autosave wrote the file.")
            ok = True
        elif saved:
            # fallback may write generated_app
            gen = workspace / "scripts" / "generated_app" / "app.py"
            if gen.is_file():
                _ok("Live LLM text-only; fallback saved scripts/generated_app/app.py.")
                ok = True
            else:
                _fail("Fallback reported write but file missing.")
                ok = False
        else:
            _fail(
                "LLM did not trigger tool_calls and no extractable code block for fallback. "
                f"reply_preview={(reply or '')[:200]!r} tools={tool_names}"
            )
            ok = False

    # Cleanup
    try:
        for folder in ("diag_test", "generated_app"):
            victim = workspace / "scripts" / folder
            if victim.is_dir():
                shutil.rmtree(victim, ignore_errors=True)
    except Exception:
        pass
    return ok


def main() -> int:
    print("[INFO] AI file-creation diagnostic suite")
    print(f"[INFO] repo_root={_REPO_ROOT}")
    results = [
        ("Test1 Direct Disk IO", test_1_direct_disk_io()),
        ("Test2 Tool Schema", test_2_tool_schema()),
        ("Test3 Tool Dispatch", test_3_tool_dispatch()),
        ("Test4 Live LLM", test_4_live_llm()),
    ]
    print("\n=== Summary ===")
    failed = 0
    for name, passed in results:
        if passed:
            _ok(name)
        else:
            _fail(name)
            failed += 1
    if failed:
        print(f"\n[ERROR] {failed} test(s) failed.")
        return 1
    print("\n[SUCCESS] All diagnostic stages passed (or skipped where expected).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
