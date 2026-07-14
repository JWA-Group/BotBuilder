"""Inventory items CRUD and smart .txt import with deduplication."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from backend.core.analytics_import import ensure_bot_user_db
from backend.core.bot_data_store import ensure_extended_bot_tables

PRODUCT_ID_RE = __import__("re").compile(r"^[A-Za-z0-9_\-]{1,64}$")
ALLOWED_STATUS = frozenset({"in_stock", "issued"})
DEFAULT_DELIMITERS = (":", ";", "|", "\t", ",")


class InventoryError(ValueError):
    """Invalid inventory operation."""


def _connect(bot_id: int) -> sqlite3.Connection:
    ensure_bot_user_db(bot_id)
    conn = sqlite3.connect(str(ensure_bot_user_db(bot_id)))
    conn.row_factory = sqlite3.Row
    ensure_extended_bot_tables(conn)
    conn.commit()
    return conn


def canonical_content(content: dict[str, Any]) -> str:
    return json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _validate_product_id(product_id: str) -> str:
    pid = (product_id or "").strip()
    if not pid or not PRODUCT_ID_RE.match(pid):
        raise InventoryError("Invalid product_id (use letters, digits, _, -)")
    return pid


def _validate_status(status: str) -> str:
    st = (status or "in_stock").strip().lower()
    if st not in ALLOWED_STATUS:
        raise InventoryError(f"Invalid status: {status!r}")
    return st


def _parse_content_value(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        raise InventoryError("content must be a JSON object")
    raise InventoryError("content must be a JSON object")


def list_product_ids(bot_id: int) -> list[str]:
    conn = _connect(bot_id)
    try:
        cur = conn.execute(
            "SELECT DISTINCT product_id FROM inventory_items ORDER BY product_id"
        )
        return [str(r[0]) for r in cur.fetchall() if r[0]]
    finally:
        conn.close()


def fetch_inventory_items(
    bot_id: int,
    *,
    product_id: str | None = None,
    limit: int = 2000,
    offset: int = 0,
) -> dict[str, Any]:
    conn = _connect(bot_id)
    try:
        params: list[Any] = []
        where = ""
        if product_id:
            where = " WHERE product_id = ?"
            params.append(_validate_product_id(product_id))
        total = conn.execute(f"SELECT COUNT(*) FROM inventory_items{where}", params).fetchone()[0]
        sql = f"""
            SELECT id, product_id, content, status, assigned_to_user, issued_at, created_at
            FROM inventory_items{where}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """
        cur = conn.execute(sql, params + [limit, offset])
        rows = [dict(row) for row in cur.fetchall()]
        return {"rows": rows, "total": int(total), "limit": limit, "offset": offset}
    finally:
        conn.close()


def create_inventory_item(
    bot_id: int,
    *,
    product_id: str,
    content: dict[str, Any] | str,
    status: str = "in_stock",
) -> dict[str, Any]:
    pid = _validate_product_id(product_id)
    st = _validate_status(status)
    payload = _parse_content_value(content)
    if not payload:
        raise InventoryError("content cannot be empty")
    now = time.time()
    conn = _connect(bot_id)
    try:
        cur = conn.execute(
            """
            INSERT INTO inventory_items (product_id, content, status, assigned_to_user, issued_at, created_at)
            VALUES (?, ?, ?, NULL, NULL, ?)
            """,
            (pid, canonical_content(payload), st, now),
        )
        conn.commit()
        item_id = int(cur.lastrowid)
    finally:
        conn.close()
    return {"ok": True, "id": item_id}


def update_inventory_item(
    bot_id: int,
    item_id: int,
    *,
    product_id: str | None = None,
    content: dict[str, Any] | str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    conn = _connect(bot_id)
    try:
        row = conn.execute(
            "SELECT id FROM inventory_items WHERE id = ?",
            (int(item_id),),
        ).fetchone()
        if not row:
            raise InventoryError("Item not found")
        updates: list[str] = []
        params: list[Any] = []
        if product_id is not None:
            updates.append("product_id = ?")
            params.append(_validate_product_id(product_id))
        if content is not None:
            payload = _parse_content_value(content)
            if not payload:
                raise InventoryError("content cannot be empty")
            updates.append("content = ?")
            params.append(canonical_content(payload))
        if status is not None:
            updates.append("status = ?")
            params.append(_validate_status(status))
        if not updates:
            raise InventoryError("No fields to update")
        params.append(int(item_id))
        conn.execute(
            f"UPDATE inventory_items SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "id": int(item_id)}


def delete_inventory_items(bot_id: int, item_ids: list[int]) -> dict[str, Any]:
    ids = sorted({int(x) for x in item_ids if int(x) > 0})
    if not ids:
        raise InventoryError("No items selected")
    conn = _connect(bot_id)
    try:
        placeholders = ",".join("?" for _ in ids)
        cur = conn.execute(
            f"DELETE FROM inventory_items WHERE id IN ({placeholders})",
            ids,
        )
        conn.commit()
        return {"ok": True, "deleted": cur.rowcount}
    finally:
        conn.close()


def detect_delimiter(sample_line: str) -> str:
    line = (sample_line or "").strip()
    if not line:
        return ":"
    counts = {d: line.count(d) for d in DEFAULT_DELIMITERS if d in line}
    if not counts:
        return ":"
    return max(counts, key=counts.get)


def _read_txt_lines(file_path: str) -> list[str]:
    path = Path(file_path).resolve()
    if not path.is_file():
        raise InventoryError(f"File not found: {file_path}")
    if path.suffix.lower() != ".txt":
        raise InventoryError("Only .txt files are supported")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp1251", errors="replace")
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _read_json_items(file_path: str) -> list[dict[str, Any]]:
    path = Path(file_path).resolve()
    if not path.is_file():
        raise InventoryError(f"File not found: {file_path}")
    if path.suffix.lower() != ".json":
        raise InventoryError("Expected a .json file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"Invalid JSON: {exc}") from exc
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        for key in ("items", "records", "data", "inventory"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                break
        else:
            raise InventoryError("JSON must be an array or contain items/records/data array")
    else:
        raise InventoryError("JSON root must be an array or object")
    parsed: list[dict[str, Any]] = []
    for raw in items:
        if isinstance(raw, dict) and raw:
            parsed.append({str(k): v for k, v in raw.items()})
    return parsed


def preview_import_file(
    file_path: str,
    *,
    delimiter: str | None = None,
    max_samples: int = 5,
) -> dict[str, Any]:
    path = Path(file_path).resolve()
    if path.suffix.lower() == ".json":
        items = _read_json_items(file_path)
        if not items:
            raise InventoryError("JSON file is empty")
        keys: list[str] = []
        seen_keys: set[str] = set()
        for item in items:
            for k in item.keys():
                ks = str(k)
                if ks not in seen_keys:
                    seen_keys.add(ks)
                    keys.append(ks)
        samples = [{"raw": json.dumps(item, ensure_ascii=False), "parts": item} for item in items[:max_samples]]
        return {
            "format": "json",
            "delimiter": "",
            "columns_count": len(keys),
            "suggested_column_map": keys,
            "sample_lines": samples,
            "total_lines": len(items),
        }
    result = preview_txt_import(file_path, delimiter=delimiter, max_samples=max_samples)
    result["format"] = "txt"
    return result


def preview_txt_import(
    file_path: str,
    *,
    delimiter: str | None = None,
    max_samples: int = 5,
) -> dict[str, Any]:
    lines = _read_txt_lines(file_path)
    if not lines:
        raise InventoryError("File is empty")
    delim = delimiter or detect_delimiter(lines[0])
    parts_count = len(lines[0].split(delim))
    samples = []
    for line in lines[:max_samples]:
        parts = [p.strip() for p in line.split(delim)]
        samples.append({"raw": line, "parts": parts})
    suggested_keys = [f"field_{i + 1}" for i in range(parts_count)]
    if parts_count == 2:
        suggested_keys = ["email", "pass"]
    return {
        "delimiter": delim,
        "columns_count": parts_count,
        "suggested_column_map": suggested_keys,
        "sample_lines": samples,
        "total_lines": len(lines),
    }


def _build_content_from_parts(
    parts: list[str],
    column_map: list[str],
    static_fields: dict[str, Any],
) -> dict[str, Any] | None:
    obj = dict(static_fields or {})
    if len(parts) < len(column_map):
        return None
    for idx, key in enumerate(column_map):
        k = str(key or "").strip()
        if not k:
            continue
        obj[k] = parts[idx].strip()
    if not obj:
        return None
    return obj


def import_inventory_txt(
    bot_id: int,
    *,
    file_path: str,
    product_id: str,
    delimiter: str,
    column_map: list[str],
    static_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pid = _validate_product_id(product_id)
    delim = (delimiter or ":").strip() or ":"
    column_map = [str(c).strip() for c in (column_map or []) if str(c).strip()]
    static_fields = dict(static_fields or {})
    path = Path(file_path).resolve()
    is_json = path.suffix.lower() == ".json"
    if is_json:
        raw_items = _read_json_items(file_path)
        if not column_map and raw_items:
            column_map = list(raw_items[0].keys())
        parsed_items: list[dict[str, Any]] = []
        seen_in_file: set[str] = set()
        errors_count = 0
        duplicates_in_file = 0
        for item in raw_items:
            content = dict(static_fields)
            content.update(item)
            if not content:
                errors_count += 1
                continue
            sig = canonical_content(content)
            if sig in seen_in_file:
                duplicates_in_file += 1
                continue
            seen_in_file.add(sig)
            parsed_items.append(content)
        lines_count = len(raw_items)
    else:
        if not column_map:
            raise InventoryError("column_map is required")
        lines = _read_txt_lines(file_path)
        seen_in_file = set()
        parsed_items = []
        errors_count = 0
        duplicates_in_file = 0

        for line in lines:
            parts = [p.strip() for p in line.split(delim)]
            content = _build_content_from_parts(parts, column_map, static_fields)
            if content is None:
                errors_count += 1
                continue
            sig = canonical_content(content)
            if sig in seen_in_file:
                duplicates_in_file += 1
                continue
            seen_in_file.add(sig)
            parsed_items.append(content)
        lines_count = len(lines)

    conn = _connect(bot_id)
    try:
        existing: set[str] = set()
        cur = conn.execute(
            "SELECT content FROM inventory_items WHERE product_id = ?",
            (pid,),
        )
        for row in cur.fetchall():
            try:
                existing.add(canonical_content(json.loads(row[0])))
            except (TypeError, json.JSONDecodeError):
                existing.add(str(row[0]))

        to_insert: list[dict[str, Any]] = []
        skipped_preview: list[str] = []
        duplicates_skipped = duplicates_in_file

        for content in parsed_items:
            sig = canonical_content(content)
            if sig in existing:
                duplicates_skipped += 1
                preview_val = content.get(column_map[0]) if column_map else next(iter(content.values()), sig)
                if preview_val and len(skipped_preview) < 20:
                    skipped_preview.append(str(preview_val))
                continue
            to_insert.append(content)
            existing.add(sig)

        successfully_imported = 0
        now = time.time()
        conn.execute("BEGIN IMMEDIATE")
        try:
            for content in to_insert:
                conn.execute(
                    """
                    INSERT INTO inventory_items (product_id, content, status, created_at)
                    VALUES (?, ?, 'in_stock', ?)
                    """,
                    (pid, canonical_content(content), now),
                )
                successfully_imported += 1
            conn.commit()
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return {
            "total_processed": lines_count,
            "successfully_imported": successfully_imported,
            "duplicates_skipped": duplicates_skipped,
            "skipped_items_preview": skipped_preview,
            "errors_count": errors_count,
            "duplicates_in_file": duplicates_in_file,
        }
    finally:
        conn.close()
