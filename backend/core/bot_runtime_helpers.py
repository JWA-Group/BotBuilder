"""Runtime helpers stitched into generated bot main.py."""

from __future__ import annotations

BUTTON_LAYOUT_HELPERS = '''

def normalize_button_row_breaks(breaks, count):
    if not count:
        return []
    raw = breaks if isinstance(breaks, list) else [0]
    out = []
    for x in raw:
        try:
            ix = int(x)
        except (TypeError, ValueError):
            continue
        if 0 <= ix < count:
            out.append(ix)
    out.sort()
    if not out or out[0] != 0:
        out.insert(0, 0)
    deduped = []
    for x in out:
        if not deduped or deduped[-1] != x:
            deduped.append(x)
    return deduped


def build_button_rows_from_breaks(items, breaks):
    """Split a flat button list into rows using row-break start indices."""
    if not items:
        return []
    n = len(items)
    b = normalize_button_row_breaks(breaks, n)
    rows = []
    for i, start in enumerate(b):
        end = b[i + 1] if i + 1 < len(b) else n
        if end > start:
            rows.append(items[start:end])
    if not rows:
        rows.append(list(items))
    return rows
'''

_NEXT_MAP_LINE = '    NEXT_MAP[(c["from"], out)] = c["to"]\n'


def ensure_button_layout_helpers(code: str) -> str:
    """Insert row-layout helpers after NEXT_MAP is built (idempotent)."""
    if "def build_button_rows_from_breaks" in code:
        return code
    if _NEXT_MAP_LINE not in code:
        return code
    return code.replace(_NEXT_MAP_LINE, _NEXT_MAP_LINE + BUTTON_LAYOUT_HELPERS + "\n", 1)
