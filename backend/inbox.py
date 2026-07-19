"""Inbox digestion (merge IA #7): list undigested notes, mark reviewed, trash.

收件匣 = notes still waiting for a human pass: frontmatter `status: inbox`, or a
note in 01_Inbox/ with no status line yet. Actions touch frontmatter lines only
(status/next_action/updated) — the body stays byte-identical. Delete is a
trash-can move into <vault_root>/_trash (double-confirmed by the caller), never
an unlink.
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

INBOX_DIRNAME = "01_Inbox"
SOURCES_DIRNAME = "02_Sources"
TRASH_DIRNAME = "_trash"
_SCAN_FILE_CAP = 2000
_HEAD_CHARS = 4000


def _head(md: Path) -> str:
    try:
        return md.read_text(encoding="utf-8", errors="ignore")[:_HEAD_CHARS]
    except OSError:
        return ""


def _scan_first(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _record(md: Path, root: Path, head: str, status: str) -> dict[str, Any]:
    rel = md.relative_to(root).as_posix()
    title = (
        _scan_first(r"(?m)^title:\s*\"?(.+?)\"?\s*$", head)
        or _scan_first(r"(?m)^#\s+(.+)$", head)
        or md.stem
    )
    parts = rel.split("/")
    return {
        "title": title,
        "path": rel,
        "source": parts[1] if len(parts) > 2 else parts[0],
        "status": status or "no_status",
        "date": _scan_first(r"(?m)^(?:clipped_at|created):\s*\"?([0-9][0-9 :\-/]+)", head),
        "source_url": _scan_first(r"(?m)^(?:url|canonical_url|source_url):\s*\"?(.+?)\"?\s*$", head),
    }


def scan_inbox(vault_root: str) -> dict[str, Any]:
    """List undigested notes: status: inbox anywhere under 01_Inbox/02_Sources,
    plus 01_Inbox notes with no status line. Skips _underscore files and readmes."""
    root = Path(str(vault_root or "")).expanduser()
    if not root.is_dir():
        return {"items": [], "total": 0}
    items: list[dict[str, Any]] = []
    for dirname in (INBOX_DIRNAME, SOURCES_DIRNAME):
        base = root / dirname
        if not base.is_dir():
            continue
        for md in sorted(base.rglob("*.md"))[:_SCAN_FILE_CAP]:
            if md.name.startswith(("_", ".")):
                continue
            head = _head(md)
            if re.search(r"(?m)^type:\s*(?:readme|index)\b", head):
                continue
            status = _scan_first(r"(?m)^status:\s*(\S+)", head)
            if status == "inbox" or (not status and dirname == INBOX_DIRNAME):
                items.append(_record(md, root, head, status))
    items.sort(key=lambda r: r["date"], reverse=True)
    return {"items": items, "total": len(items)}


def _bounded(vault_root: str, note_relpath: str) -> Path:
    from app_state import bounded_relative_child_path

    return bounded_relative_child_path(vault_root, note_relpath)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def mark_reviewed(vault_root: str, note_relpath: str) -> dict[str, Any]:
    """status: inbox → reviewed, next_action → none, updated → today.
    Frontmatter lines only; raises ValueError when the note has no inbox status."""
    target = _bounded(vault_root, note_relpath)
    if not target.is_file():
        raise FileNotFoundError(f"note not found: {note_relpath}")
    content = target.read_text(encoding="utf-8")
    new_content, replaced = re.subn(r"(?m)^status:\s*inbox\s*$", "status: reviewed", content, count=1)
    if not replaced:
        raise ValueError("note has no 'status: inbox' frontmatter line to review")
    new_content = re.sub(r"(?m)^next_action:\s*.*$", "next_action: none", new_content, count=1)
    today = datetime.now().strftime("%Y-%m-%d")
    new_content = re.sub(r"(?m)^updated:\s*.*$", f"updated: {today}", new_content, count=1)
    _atomic_write(target, new_content)
    return {"ok": True, "path": note_relpath, "status": "reviewed", "updated": today}


def trash_note(vault_root: str, note_relpath: str) -> dict[str, Any]:
    """Move the note into <vault_root>/_trash with a date prefix (no unlink)."""
    target = _bounded(vault_root, note_relpath)
    if not target.is_file():
        raise FileNotFoundError(f"note not found: {note_relpath}")
    trash_dir = Path(str(vault_root)).expanduser() / TRASH_DIRNAME
    trash_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    destination = trash_dir / f"{stamp}_{target.name}"
    counter = 2
    while destination.exists():
        destination = trash_dir / f"{stamp}_{target.stem}-{counter}{target.suffix}"
        counter += 1
    shutil.move(str(target), str(destination))
    rel = destination.relative_to(Path(str(vault_root)).expanduser()).as_posix()
    return {"ok": True, "path": note_relpath, "trashed_to": rel}
