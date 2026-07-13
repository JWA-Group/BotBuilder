"""Scenario version history — rotate backups under projects/bot_{id}/.history/."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

MAX_VERSIONS = 30
RETENTION_SECONDS = 12 * 60 * 60  # 12 hours — discard older snapshots to save disk space
_VERSION_RE = re.compile(r"^version_(\d+)\.json$")

from backend.core.app_paths import PROJECTS_DIR as DEFAULT_PROJECTS_DIR


def projects_root(base: Path | str | None = None) -> Path:
    return Path(base) if base else DEFAULT_PROJECTS_DIR


def history_dir(base: Path | str | None, bot_id: int) -> Path:
    return projects_root(base) / f"bot_{bot_id}" / ".history"


def scenario_path(base: Path | str | None, bot_id: int) -> Path:
    return projects_root(base) / f"bot_{bot_id}" / "scenario.json"


def _version_path(hdir: Path, timestamp: int) -> Path:
    return hdir / f"version_{int(timestamp)}.json"


def _meta_path(hdir: Path, timestamp: int) -> Path:
    return hdir / f"version_{int(timestamp)}.meta.json"


def _list_version_files(hdir: Path) -> list[tuple[int, Path]]:
    if not hdir.is_dir():
        return []
    out: list[tuple[int, Path]] = []
    for path in hdir.iterdir():
        if not path.is_file():
            continue
        m = _VERSION_RE.match(path.name)
        if m:
            out.append((int(m.group(1)), path))
    out.sort(key=lambda x: x[0])
    return out


def _purge_expired(hdir: Path) -> None:
    """Remove version files older than RETENTION_SECONDS."""
    cutoff = int(time.time()) - RETENTION_SECONDS
    for ts, path in _list_version_files(hdir):
        if ts < cutoff:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                _meta_path(hdir, ts).unlink(missing_ok=True)
            except OSError:
                pass


def _prune_versions_newer_than(hdir: Path, timestamp: int) -> None:
    """Drop snapshots newer than the restored point (abandoned timeline branch)."""
    for ts, path in _list_version_files(hdir):
        if ts > int(timestamp):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                _meta_path(hdir, ts).unlink(missing_ok=True)
            except OSError:
                pass


def _rotate(hdir: Path) -> None:
    entries = _list_version_files(hdir)
    while len(entries) > MAX_VERSIONS:
        ts, path = entries.pop(0)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            _meta_path(hdir, ts).unlink(missing_ok=True)
        except OSError:
            pass
    _purge_expired(hdir)


def archive_scenario(
    bot_id: int,
    scenario: dict[str, Any],
    *,
    kind: str = "user",
    projects_dir: Path | str | None = None,
) -> int:
    """
    Write a timestamped backup of scenario JSON and enforce MAX_VERSIONS rotation.
    Returns unix timestamp of the new version.
    """
    hdir = history_dir(projects_dir, bot_id)
    hdir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    while _version_path(hdir, ts).exists():
        ts += 1
    payload = json.dumps(scenario, ensure_ascii=False, indent=2)
    _version_path(hdir, ts).write_text(payload, encoding="utf-8")
    _meta_path(hdir, ts).write_text(
        json.dumps({"kind": kind, "timestamp": ts}, ensure_ascii=False),
        encoding="utf-8",
    )
    _rotate(hdir)
    return ts


def list_versions(
    bot_id: int,
    *,
    projects_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Sorted metadata for available rollback points (oldest → newest)."""
    hdir = history_dir(projects_dir, bot_id)
    _purge_expired(hdir)
    entries = _list_version_files(hdir)
    result: list[dict[str, Any]] = []
    for ts, path in entries:
        kind = "user"
        meta_file = _meta_path(hdir, ts)
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                kind = str(meta.get("kind") or "user")
            except (OSError, json.JSONDecodeError):
                pass
        result.append(
            {
                "timestamp": ts,
                "kind": kind,
                "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)),
            }
        )
    return result


def load_version(
    bot_id: int,
    timestamp: int,
    *,
    projects_dir: Path | str | None = None,
) -> dict[str, Any]:
    hdir = history_dir(projects_dir, bot_id)
    path = _version_path(hdir, int(timestamp))
    if not path.is_file():
        raise FileNotFoundError(f"Version {timestamp} not found")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid scenario snapshot")
    return data


def restore_version(
    bot_id: int,
    timestamp: int,
    *,
    projects_dir: Path | str | None = None,
) -> tuple[dict[str, Any], int]:
    """
    Overwrite live scenario.json with a historical snapshot.
    Prunes newer history entries, archives restored state as the latest version.
    Returns (restored payload, new version timestamp).
    """
    ts = int(timestamp)
    data = load_version(bot_id, ts, projects_dir=projects_dir)
    dest = scenario_path(projects_dir, bot_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    hdir = history_dir(projects_dir, bot_id)
    _prune_versions_newer_than(hdir, ts)
    _purge_expired(hdir)
    new_ts = archive_scenario(bot_id, data, kind="user", projects_dir=projects_dir)
    return data, new_ts


def ensure_baseline_version(
    bot_id: int,
    *,
    projects_dir: Path | str | None = None,
) -> int | None:
    """Create first history entry from live scenario.json when history is empty."""
    hdir = history_dir(projects_dir, bot_id)
    if _list_version_files(hdir):
        return None
    live = scenario_path(projects_dir, bot_id)
    if not live.is_file():
        return None
    try:
        data = json.loads(live.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return archive_scenario(bot_id, data, kind="user", projects_dir=projects_dir)
