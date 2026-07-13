"""Verify href/src asset paths under frontend/ resolve on disk."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend"
ATTR_RE = re.compile(r"""(?:href|src)=["']([^"'#?]+)""", re.I)

missing: list[tuple[str, str, str]] = []
checked = 0

for path in ROOT.rglob("*"):
    if path.suffix.lower() not in {".html", ".js", ".css"}:
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    for match in ATTR_RE.finditer(text):
        url = match.group(1)
        if url.startswith(("http://", "https://", "data:", "//", "mailto:", "javascript:")):
            continue
        if url.startswith("/api"):
            continue
        checked += 1
        if url.startswith("/"):
            rel = url.lstrip("/")
            if rel in {"manifest.webmanifest", "manifest"}:
                target = ROOT / "manifest.webmanifest"
            elif url.endswith("/"):
                target = ROOT / rel.rstrip("/") / "index.html"
            else:
                target = ROOT / rel
            if not target.exists():
                missing.append((str(path.relative_to(ROOT.parent)), url, str(target)))
        else:
            target = (path.parent / url).resolve()
            if not target.exists():
                missing.append((str(path.relative_to(ROOT.parent)), url, str(target)))

print(f"checked={checked} missing={len(missing)}")
for item in missing:
    print("MISS", item[0], "->", item[1])
raise SystemExit(1 if missing else 0)
