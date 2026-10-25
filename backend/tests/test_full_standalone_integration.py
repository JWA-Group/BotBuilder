#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Master Integration Test Suite: standalone app pipeline end to end.

  1. Disk I/O            write_workspace_file -> scripts/master_test_app/
  2. Port/node integrity create_complete_standalone_app wiring + sanitizing
  3. Compiler            generate_main_from_scenario -> valid main.py
  4. File tree           /api/repository/tree lists scripts/master_test_app
  5. Cleanup             remove the dedicated test bot workspace

Run from repo root:
  python backend/tests/test_full_standalone_integration.py

Uses a dedicated bot workspace (bot_990099) so real bots are never touched.
"""

from __future__ import annotations

import asyncio
import json
import py_compile
import re
import shutil
import sys
import traceback
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

TEST_BOT_ID = 990099
APP_NAME = "master_test_app"
APP_REL = f"scripts/{APP_NAME}"

APP_CODE = '''"""Master integration test app."""


async def main(**kwargs):
    return {"ok": True, "result": "master-test", "inputs": kwargs}
'''

SEED_SCENARIO = {
    "blocks": [
        {"id": "start_1", "type": "start", "x": 60, "y": 120, "data": {}},
        {"id": "note_1", "type": "note", "x": 60, "y": 320, "data": {"text": "seed"}},
    ],
    "connections": [
        {"from": "start_1", "to": "deleted_block", "outputIndex": "0"},
        {"from": "ghost_block", "to": "start_1", "outputIndex": "0"},
    ],
    "tags": [],
}


def _pass(msg: str) -> None:
    print(f"[PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def _info(msg: str) -> None:
    print(f"[INFO] {msg}")


def _workspace() -> Path:
    from backend.services.ai_tools import get_bot_workspace_dir

    return get_bot_workspace_dir(TEST_BOT_ID)


def _seed_workspace() -> Path:
    root = _workspace()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "scenario.json").write_text(
        json.dumps(SEED_SCENARIO, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return root


def test_1_disk_io() -> bool:
    print("\n=== Test 1: Disk I/O ===")
    from backend.services.ai_tools import write_workspace_file

    root = _workspace()
    rel = f"{APP_REL}/probe.py"
    res = write_workspace_file(TEST_BOT_ID, rel, "VALUE = 1\n")
    if not (res.get("ok") or res.get("success")):
        _fail(f"write_workspace_file returned error: {res.get('error')}")
        return False
    target = root / rel
    if not target.is_file():
        _fail(f"file missing on disk: {target}")
        return False
    if target.read_text(encoding="utf-8") != "VALUE = 1\n":
        _fail("file content mismatch")
        return False
    _pass(f"physical file written: {target}")
    return True


def test_2_port_node_integrity() -> bool:
    print("\n=== Test 2: Port and Node Integrity ===")
    import backend.services.ai_tools as ai_tools
    from backend.services.ai_tools import _block_output_count, create_complete_standalone_app

    root = _workspace()
    result = create_complete_standalone_app(
        bot_id=TEST_BOT_ID,
        app_name=APP_NAME,
        script_code=APP_CODE,
        manifest={"description": "master test", "outputs": ["has_items", "no_new_items", "error"]},
        nodes_to_add=[
            {"id": "msg_done", "type": "message", "x": 700, "y": 80, "data": {"text": "done"}},
            {"id": "msg_fail", "type": "message", "x": 700, "y": 300, "data": {"text": "fail"}},
        ],
        connections_to_add=[
            {"from": "app_bridge", "to": "msg_done", "from_port": "has_items"},
            {"from_node": "app_bridge", "to_node": "msg_fail", "from_port": "port_out_1"},
            {"from": "msg_done", "to": "msg_done"},
            {"from": "msg_fail", "to": "missing_target"},
        ],
        wire_default_messages=False,
    )
    ok = True

    if not result.get("success"):
        _fail(f"tool failed: {result.get('error')}")
        return False
    if not (result.get("refresh_canvas") and result.get("refresh_repo")):
        _fail("refresh_canvas / refresh_repo flags missing")
        ok = False
    else:
        _pass("refresh_canvas and refresh_repo flags set")

    for rel in (f"{APP_REL}/app.py", f"{APP_REL}/manifest.json"):
        if not (root / rel).is_file():
            _fail(f"missing on disk: {rel}")
            ok = False
    if ok:
        _pass("app.py and manifest.json exist on disk")

    sc = json.loads((root / "scenario.json").read_text(encoding="utf-8"))
    blocks = {b["id"]: b for b in sc.get("blocks") or []}
    bridge = next((b for b in blocks.values() if b.get("type") == "app_bridge"), None)
    if not bridge:
        _fail("app_bridge node not persisted in scenario.json")
        return False
    bdata = bridge.get("data") or {}
    if bdata.get("appFolder") != APP_REL or bdata.get("entryFile") != "app.py":
        _fail(f"bridge data mismatch: appFolder={bdata.get('appFolder')} entryFile={bdata.get('entryFile')}")
        ok = False
    else:
        _pass(f"app_bridge node {bridge['id']} points to {APP_REL}/app.py")

    bad = []
    for c in sc.get("connections") or []:
        frm, to, idx = c.get("from"), c.get("to"), c.get("outputIndex")
        if frm not in blocks or to not in blocks:
            bad.append((c, "orphan"))
            continue
        count = _block_output_count(blocks[frm])
        if not str(idx).isdigit() or (count is not None and int(idx) >= count):
            bad.append((c, f"port {idx} out of range {count}"))
    if bad:
        _fail(f"broken connections remain: {bad}")
        ok = False
    else:
        _pass(f"all {len(sc.get('connections') or [])} connections resolve to existing nodes and ports")

    edges = {(c["from"], c["outputIndex"]): c["to"] for c in sc.get("connections") or []}
    expected = {
        (bridge["id"], "0"): "msg_done",
        (bridge["id"], "1"): "msg_fail",
        ("start_1", "0"): bridge["id"],
    }
    for key, to in expected.items():
        if edges.get(key) != to:
            _fail(f"expected edge {key[0]}[{key[1]}] -> {to}, got {edges.get(key)}")
            ok = False
    if all(edges.get(k) == v for k, v in expected.items()):
        _pass("ports aligned: start -> bridge, bridge[0] -> msg_done, bridge[1] -> msg_fail")

    reasons = sorted({r["reason"] for r in result.get("connections_removed") or []})
    if len(result.get("connections_removed") or []) < 2:
        _fail(f"sanitizer did not strip seed orphans: {reasons}")
        ok = False
    else:
        _pass(f"sanitizer stripped {len(result['connections_removed'])} broken edge(s): {reasons}")
    if result.get("scenario", {}).get("connections") != sc.get("connections"):
        _fail("returned scenario differs from scenario.json on disk")
        ok = False

    # Strict I/O: a failed write must raise, not return a silent success.
    original = ai_tools.write_workspace_file
    ai_tools.write_workspace_file = lambda *a, **k: {"ok": False, "success": False, "error": "simulated"}
    try:
        create_complete_standalone_app(
            bot_id=TEST_BOT_ID, app_name="io_fail_app", script_code=APP_CODE
        )
        _fail("simulated disk failure did not raise")
        ok = False
    except RuntimeError as exc:
        _pass(f"disk failure raises RuntimeError: {exc}")
    finally:
        ai_tools.write_workspace_file = original
    return ok


def test_3_compiler() -> bool:
    print("\n=== Test 3: Compiler ===")
    from backend.utils.generate_main import generate_main_from_scenario

    root = _workspace()
    if not generate_main_from_scenario(TEST_BOT_ID):
        _fail("generate_main_from_scenario returned False (see compile logs)")
        return False
    main_py = root / "main.py"
    if not main_py.is_file():
        _fail(f"main.py not generated at {main_py}")
        return False
    src = main_py.read_text(encoding="utf-8")
    try:
        py_compile.compile(str(main_py), doraise=True)
    except py_compile.PyCompileError as exc:
        _fail(f"main.py has syntax errors: {exc.msg}")
        return False
    ok = True
    if "_type_handler_app_bridge" not in src:
        _fail("app_bridge handler missing from main.py")
        ok = False
    if "{{" in src and "{%" in src:
        _fail("unrendered Jinja markup leaked into main.py")
        ok = False
    if ok:
        _pass(f"main.py compiled ({len(src)} chars) with app_bridge handler")
    return ok


def test_4_file_tree() -> bool:
    print("\n=== Test 4: File Tree Inspection ===")
    import backend.routes.repository as repo

    async def _no_guard(*_a, **_k):
        return None

    original_guard = repo._guard
    repo._guard = _no_guard
    try:
        tree = asyncio.run(repo.repository_tree(bot_id=TEST_BOT_ID, user_id=1, db=None))
    finally:
        repo._guard = original_guard

    def find(node, path):
        if node.get("path") == path:
            return node
        for ch in node.get("children") or []:
            hit = find(ch, path)
            if hit:
                return hit
        return None

    folder = find(tree, APP_REL)
    if not folder or folder.get("type") != "dir":
        _fail(f"{APP_REL} not present in /api/repository/tree")
        return False
    names = sorted(ch.get("name") for ch in folder.get("children") or [])
    if "app.py" not in names or "manifest.json" not in names:
        _fail(f"{APP_REL} children incomplete: {names}")
        return False
    _pass(f"/api/repository/tree lists {APP_REL}: {names}")
    return True


def test_6_session_bot_binding() -> bool:
    print("\n=== Test 6: Session Bot Binding ===")
    from backend.core.app_paths import PROJECTS_DIR
    from backend.routes.ai_assistant import _AgentState
    from backend.services.ai_tools import get_bot_workspace_dir

    phantom = PROJECTS_DIR / "bot_default"
    phantom_existed = phantom.exists()
    ok = True

    try:
        get_bot_workspace_dir("default")
        _fail("get_bot_workspace_dir accepted non-numeric id 'default'")
        ok = False
    except ValueError:
        _pass("non-numeric bot ids are rejected")

    no_bot = _AgentState(current_scenario={}, messages=[], bot_id=None)
    res = asyncio.run(
        no_bot.execute(
            "write_workspace_file",
            {"relative_path": "scripts/x/app.py", "content": "X = 1\n", "bot_id": "default"},
        )
    )
    if res.get("ok") or (not phantom_existed and phantom.exists()):
        _fail(f"tool wrote without a session bot: {res}")
        ok = False
    else:
        _pass("without a session bot, file tools refuse instead of inventing a workspace")

    state = _AgentState(current_scenario={}, messages=[], bot_id=TEST_BOT_ID)
    res = asyncio.run(
        state.execute(
            "write_workspace_file",
            {"relative_path": f"{APP_REL}/bound.py", "content": "Y = 2\n", "bot_id": "default"},
        )
    )
    if not res.get("ok") or not (_workspace() / APP_REL / "bound.py").is_file():
        _fail(f"model bot_id overrode the session bot: {res}")
        ok = False
    else:
        _pass("model-supplied bot_id is ignored, file lands in the session bot")
    return ok


def test_7_named_ports_and_fanout() -> bool:
    print("\n=== Test 7: Named Ports and Fan-out ===")
    from backend.services.ai_scenario_ops import catalog_types, finalize_scenario

    raw = {
        "blocks": [
            {"id": "start", "type": "start", "x": 0, "y": 0, "data": {}},
            {"id": "bridge", "type": "app_bridge", "x": 300, "y": 0, "data": {"appFolder": APP_REL}},
            {"id": "ok_msg", "type": "message", "x": 600, "y": 0, "data": {"text": "ok"}},
            {"id": "err_msg", "type": "message", "x": 600, "y": 200, "data": {"text": "err"}},
            {"id": "other", "type": "message", "x": 300, "y": 300, "data": {"text": "other"}},
        ],
        "connections": [
            {"from": "start", "to": "other", "outputIndex": "0"},
            {"from": "start", "to": "bridge", "outputIndex": "0"},
            {"from": "bridge", "to": "ok_msg", "outputIndex": "has_items"},
            {"from": "bridge", "to": "err_msg", "outputIndex": "error"},
            {"from": "ok_msg", "to": "err_msg", "outputIndex": "has_data"},
            {"from": "other", "to": "ok_msg", "outputIndex": "weird_name"},
        ],
    }
    sc = finalize_scenario(raw, catalog_types() | {"app_bridge", "message", "start"})
    edges = {(c["from"], c["outputIndex"]): c["to"] for c in sc["connections"]}
    ok = True
    if any(not str(c["outputIndex"]).isdigit() for c in sc["connections"]):
        _fail(f"non-numeric outputIndex survived: {sc['connections']}")
        ok = False
    if edges.get(("bridge", "0")) != "ok_msg" or edges.get(("bridge", "1")) != "err_msg":
        _fail(f"bridge ports not mapped to 0/1: {edges}")
        ok = False
    if sum(1 for c in sc["connections"] if c["from"] == "start") != 1:
        _fail("start keeps several targets on one port")
        ok = False
    if ("other", "0") in edges:
        _fail("unknown port name was routed instead of dropped")
        ok = False
    if ok:
        _pass(f"named ports normalized, fan-out collapsed, unknown ports dropped: {sorted(edges)}")

    main_py = _workspace() / "main.py"
    src = main_py.read_text(encoding="utf-8") if main_py.is_file() else ""
    if "BB_SCENARIO_ERROR invalid outputIndex" not in src or "import logging" not in src:
        _fail("generated main.py still routes named ports silently to port 0")
        ok = False
    else:
        _pass("generated runtime ignores and logs non-numeric ports")
    return ok


def test_8_token_limits_and_splitting() -> bool:
    print("\n=== Test 8: Token Limits and Auto-Split ===")
    from backend.services import ai_provider as ap

    ok = True
    deepseek_err = "Invalid max_tokens value, the valid range of max_tokens is [1, 8192]"
    openai_err = "max_tokens is too large: 65536. This model supports at most 16384 completion tokens"
    ctx_err = ("This model's maximum context length is 65536 tokens. However, you requested "
               "73000 tokens (8000 in the messages, 65000 in the completion).")
    got = (
        ap._cap_from_limit_error(deepseek_err, 65536),
        ap._cap_from_limit_error(openai_err, 65536),
        ap._cap_from_limit_error(ctx_err, 65000),
        ap._cap_from_limit_error("invalid api key", 65536),
    )
    if got[0] != 8192 or got[1] != 16384 or not got[2] or got[2] > 57536 or got[3] is not None:
        _fail(f"provider cap parsing wrong: {got}")
        ok = False
    else:
        _pass(f"real output cap learned from provider errors: {got[:3]}")

    provider = ap.AIProvider.__new__(ap.AIProvider)
    provider.config = type("Cfg", (), {"model": "fake-model"})()
    calls: list[dict] = []
    ran: list[str] = []

    def install(script):
        async def fake(self, messages, system_prompt, **kw):
            calls.append(kw)
            return script[min(len(calls) - 1, len(script) - 1)]
        ap.AIProvider.complete_raw = fake

    async def executor(name, args):
        ran.append(name)
        return {"ok": True}

    cut = {"content": "", "tool_calls": [{"id": "1", "function": {"name": "write_workspace_file",
           "arguments": '{"relative_path": "scripts/a/app.py", "content": "pri'}}],
           "_finish_reason": "length"}
    good = {"content": "", "tool_calls": [{"id": "2", "function": {"name": "write_workspace_file",
            "arguments": '{"relative_path": "scripts/a/app.py", "content": "X = 1"}'}}],
            "_finish_reason": "tool_calls"}
    final = {"content": "Скрипт обновлен.", "tool_calls": None, "_finish_reason": "stop"}
    tools = [{"type": "function", "function": {"name": n}} for n in ("write_workspace_file", "plan_task")]
    original = ap.AIProvider.complete_raw
    try:
        install([cut, good, final])
        asyncio.run(provider.run_tool_loop([], "sys", tools, executor, max_tokens=ap.SUBTASK_MAX_TOKENS))
        if ran != ["write_workspace_file"] or calls[0]["max_tokens"] != ap.SUBTASK_MAX_TOKENS \
                or calls[1]["max_tokens"] != ap.UNLIMITED_MAX_TOKENS:
            _fail(f"small budget did not escalate to model max: {[c['max_tokens'] for c in calls]} ran={ran}")
            ok = False
        else:
            _pass("small budget first, truncated call discarded, retried at model maximum")

        calls.clear(); ran.clear()
        install([cut, cut, good, final])
        asyncio.run(provider.run_tool_loop([], "sys", tools, executor, split_tool="plan_task"))
        forced = next((c.get("tool_choice") for c in calls if isinstance(c.get("tool_choice"), dict)), None)
        if not (forced and forced["function"]["name"] == "plan_task"):
            _fail(f"task too big for max output was not forced into plan_task: {forced}")
            ok = False
        else:
            _pass("task too big even at maximum output is forced to split via plan_task")

        calls.clear(); ran.clear()
        install([cut])
        reply, _ = asyncio.run(provider.run_tool_loop([], "sys", tools[:1], executor))
        if ran or not reply.startswith("SUBTASK_TOO_LARGE"):
            _fail(f"subtask overflow not reported to parent: {reply!r}")
            ok = False
        else:
            _pass("subtask that still does not fit asks the parent to split it further")

        install([{"content": "", "tool_calls": None, "_finish_reason": "stop"}])
        reply, _ = asyncio.run(provider.run_tool_loop([], "sys", tools, executor))
        if not reply.startswith("Изменения не применены"):
            _fail(f"empty reply masked as success: {reply!r}")
            ok = False
        else:
            _pass("empty model reply reported honestly")

        calls.clear(); ran.clear()
        install([good])
        reply, _ = asyncio.run(provider.run_tool_loop([], "sys", tools, executor, max_rounds=50))
        if len(ran) != ap.MAX_REPEATED_CALLS or not reply.startswith("Агент остановлен"):
            _fail(f"loop guard did not stop identical repeated calls: ran={len(ran)} {reply!r}")
            ok = False
        else:
            _pass(f"no fixed step cap needed: identical call stopped after {len(ran)} repeats")
    finally:
        ap.AIProvider.complete_raw = original
    return ok


def test_9_plan_and_assemble() -> bool:
    print("\n=== Test 9: Plan, Execute Subtasks, Verify ===")
    from backend.routes.ai_assistant import BOTCOPILOT_TOOLS, _AgentState
    from backend.services import ai_provider as ap

    files = {
        1: (f"{APP_REL}/fetcher.py", "def fetch():\n    return [1, 2, 3]\n"),
        2: (f"{APP_REL}/formatter.py", "def fmt(items:\n    return str(items)\n"),
    }
    seen_subtask_tools: list[set] = []

    async def fake(self, messages, system_prompt, **kw):
        first = str(messages[0].get("content") or "") if messages else ""
        last = messages[-1] if messages else {}
        m = re.search(r"YOUR SUBTASK \((\d+)/", first)
        if m:
            seen_subtask_tools.append({t["function"]["name"] for t in kw.get("tools") or []})
            if last.get("role") == "tool":
                return {"content": "done", "tool_calls": None, "_finish_reason": "stop"}
            rel, code = files[int(m.group(1))]
            args = json.dumps({"relative_path": rel, "content": code})
            return {"content": "", "_finish_reason": "tool_calls",
                    "tool_calls": [{"id": f"s{m.group(1)}", "function": {"name": "write_workspace_file", "arguments": args}}]}
        if last.get("role") == "tool":
            return {"content": "Собрано.", "tool_calls": None, "_finish_reason": "stop"}
        plan = {"goal": "two-module app", "shared_contract": "fetch() -> list; fmt(list) -> str",
                "subtasks": [{"title": "fetcher", "instructions": "write fetcher", "files": [files[1][0]]},
                             {"title": "formatter", "instructions": "write formatter", "files": [files[2][0]]}]}
        return {"content": "", "_finish_reason": "tool_calls",
                "tool_calls": [{"id": "p", "function": {"name": "plan_task", "arguments": json.dumps(plan)}}]}

    provider = ap.AIProvider.__new__(ap.AIProvider)
    provider.config = type("Cfg", (), {"model": "fake-model"})()
    state = _AgentState(current_scenario={}, messages=[], bot_id=TEST_BOT_ID)
    state.provider, state.system_prompt, state.model = provider, "sys", "fake-model"
    original = ap.AIProvider.complete_raw
    ap.AIProvider.complete_raw = fake
    try:
        reply, executed = asyncio.run(provider.run_tool_loop(
            [{"role": "user", "content": "build a big app"}], "sys", BOTCOPILOT_TOOLS,
            state.execute, split_tool="plan_task"))
    finally:
        ap.AIProvider.complete_raw = original

    ok = True
    plan_res = next((e["result"] for e in executed if e["name"] == "plan_task"), None)
    if not plan_res or len(plan_res.get("subtasks") or []) != 2:
        _fail(f"plan_task did not run both subtasks: {plan_res}")
        return False
    for rel, _ in files.values():
        if not (_workspace() / rel).is_file():
            _fail(f"subtask file missing: {rel}")
            ok = False
    if any("plan_task" in s for s in seen_subtask_tools):
        _fail("subtasks can call plan_task recursively without limit")
        ok = False
    errs = plan_res["verification"]["errors"]
    if plan_res["all_done"] or not any("formatter.py" in e for e in errs):
        _fail(f"verification missed the syntax error: {plan_res['verification']}")
        ok = False
    if ok:
        _pass("2 subtasks ran separately, files written, syntax error in formatter.py caught")
        _pass(f"main agent got results back for assembly, final reply: {reply!r}")
    return ok


def test_10_progress_and_cancel() -> bool:
    print("\n=== Test 10: Live Progress and Stop Button ===")
    import time
    from backend.services import ai_progress
    from backend.services import ai_provider as ap

    ok = True
    rid = "test-progress-1"
    ai_progress.start(rid)
    ai_progress.emit(rid, "Часть 1 из 2: parser.py", kind="plan")
    ai_progress.emit(rid, "Записываю файл", kind="tool")
    snap = ai_progress.snapshot(rid)
    tail = ai_progress.snapshot(rid, after=snap["events"][0]["seq"])
    if len(snap["events"]) != 2 or len(tail["events"]) != 1 or snap["done"]:
        _fail(f"progress snapshot wrong: {snap} / {tail}")
        ok = False
    else:
        _pass("progress events are recorded and polled incrementally")
    ai_progress.finish(rid)
    if not ai_progress.snapshot(rid)["done"]:
        _fail("finish() did not mark the request done")
        ok = False

    provider = ap.AIProvider.__new__(ap.AIProvider)
    provider.config = type("Cfg", (), {"model": "fake-model"})()
    ran: list[str] = []
    events: list[tuple[str, str]] = []

    async def slow(self, messages, system_prompt, **kw):
        await asyncio.sleep(30)
        return {"content": "never", "tool_calls": None, "_finish_reason": "stop"}

    async def executor(name, args):
        ran.append(name)
        return {"ok": True}

    rid = "test-cancel-1"
    ai_progress.start(rid)
    original = ap.AIProvider.complete_raw
    ap.AIProvider.complete_raw = slow
    started = time.monotonic()

    async def run():
        async def press_stop():
            await asyncio.sleep(0.3)
            ai_progress.cancel(rid)
        asyncio.create_task(press_stop())
        return await provider.run_tool_loop(
            [], "sys", [], executor,
            on_event=lambda k, t: events.append((k, t)),
            should_stop=lambda: ai_progress.is_cancelled(rid),
        )

    try:
        reply, _ = asyncio.run(run())
    finally:
        ap.AIProvider.complete_raw = original
        ai_progress.finish(rid)
    elapsed = time.monotonic() - started
    if reply != ap.CANCELLED_REPLY or elapsed > 5 or ran:
        _fail(f"stop did not interrupt the model: reply={reply!r} elapsed={elapsed:.1f}s ran={ran}")
        ok = False
    else:
        _pass(f"Stop interrupted a running model call in {elapsed:.1f}s")
    if not any(k == "think" for k, _ in events):
        _fail(f"no progress events from the tool loop: {events}")
        ok = False
    else:
        _pass("tool loop reports its steps to the progress feed")
    return ok


def test_5_cleanup() -> bool:
    print("\n=== Test 5: Cleanup ===")
    root = _workspace()
    try:
        if root.exists():
            shutil.rmtree(root)
    except OSError as exc:
        _fail(f"could not remove {root}: {exc}")
        return False
    if root.exists():
        _fail(f"{root} still exists")
        return False
    _pass(f"test workspace removed: {root}")
    return True


def main() -> int:
    root = _seed_workspace()
    _info(f"test workspace: {root}")
    tests = [
        test_1_disk_io,
        test_2_port_node_integrity,
        test_3_compiler,
        test_4_file_tree,
        test_6_session_bot_binding,
        test_7_named_ports_and_fanout,
        test_8_token_limits_and_splitting,
        test_9_plan_and_assemble,
        test_10_progress_and_cancel,
    ]
    results: list[bool] = []
    try:
        for fn in tests:
            try:
                results.append(bool(fn()))
            except Exception as exc:
                _fail(f"{fn.__name__} raised {type(exc).__name__}: {exc}")
                traceback.print_exc()
                results.append(False)
    finally:
        results.append(test_5_cleanup())

    passed = sum(results)
    print(f"\n=== Summary: {passed}/{len(results)} tests passed ===")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
