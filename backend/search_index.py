"""Full-text search over the vault (merge IA Batch A-①).

Persistent FTS5 index per vault root, stored under the app config dir (never
inside the user's vault). The trigram tokenizer gives CJK substring matching;
queries shorter than 3 chars fall back to a LIKE scan. Refresh is incremental
by mtime, so搜尋前的更新只重讀有變動的檔案.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

SCAN_DIRS = ("01_Inbox", "02_Sources")
_SCAN_FILE_CAP = 5000
_MAX_BODY_CHARS = 200_000


def _index_dir() -> Path:
    base = Path(os.getenv("YT_NOTE_APP_CONFIG_DIR", str(Path.home() / ".config" / "yt-note-app")))
    return base / "search"


def _db_path(vault_root: Path) -> Path:
    digest = hashlib.sha256(str(vault_root).encode("utf-8")).hexdigest()[:16]
    directory = _index_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{digest}.sqlite"


def _connect(vault_root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(vault_root))
    conn.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, mtime REAL)")
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS notes USING fts5(path UNINDEXED, title, body, tokenize='trigram')"
    )
    return conn


def _scan_first(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _walk_md(root: Path) -> dict[str, float]:
    found: dict[str, float] = {}
    for dirname in SCAN_DIRS:
        base = root / dirname
        if not base.is_dir():
            continue
        for md in sorted(base.rglob("*.md"))[:_SCAN_FILE_CAP]:
            if md.name.startswith(("_", ".")):
                continue
            try:
                found[md.relative_to(root).as_posix()] = md.stat().st_mtime
            except OSError:
                continue
    return found


def refresh_index(vault_root: str) -> dict[str, int]:
    """Incremental sync: (re)index changed/new files, drop removed ones."""
    root = Path(str(vault_root or "")).expanduser()
    if not root.is_dir():
        return {"indexed": 0, "removed": 0, "total": 0}
    on_disk = _walk_md(root)
    conn = _connect(root)
    try:
        indexed = dict(conn.execute("SELECT path, mtime FROM files").fetchall())
        stale = [p for p, m in on_disk.items() if indexed.get(p) != m]
        removed = [p for p in indexed if p not in on_disk]
        for rel in stale:
            try:
                text = (root / rel).read_text(encoding="utf-8", errors="ignore")[:_MAX_BODY_CHARS]
            except OSError:
                continue
            title = (
                _scan_first(r"(?m)^title:\s*\"?(.+?)\"?\s*$", text)
                or _scan_first(r"(?m)^#\s+(.+)$", text)
                or Path(rel).stem
            )
            conn.execute("DELETE FROM notes WHERE path = ?", (rel,))
            conn.execute("INSERT INTO notes (path, title, body) VALUES (?, ?, ?)", (rel, title, text))
            conn.execute(
                "INSERT INTO files (path, mtime) VALUES (?, ?) "
                "ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime",
                (rel, on_disk[rel]),
            )
        for rel in removed:
            conn.execute("DELETE FROM notes WHERE path = ?", (rel,))
            conn.execute("DELETE FROM files WHERE path = ?", (rel,))
        conn.commit()
        return {"indexed": len(stale), "removed": len(removed), "total": len(on_disk)}
    finally:
        conn.close()


def search_notes(vault_root: str, query: str, limit: int = 50) -> dict[str, Any]:
    root = Path(str(vault_root or "")).expanduser()
    text = str(query or "").strip()
    if not root.is_dir() or not text:
        return {"records": [], "total": 0}
    stats = refresh_index(vault_root)
    conn = _connect(root)
    limit = max(1, min(int(limit or 50), 200))
    try:
        if len(text) >= 3:
            escaped = text.replace('"', '""')
            rows = conn.execute(
                "SELECT path, title, snippet(notes, 2, '[', ']', '…', 12) FROM notes "
                "WHERE notes MATCH ? ORDER BY rank LIMIT ?",
                (f'"{escaped}"', limit),
            ).fetchall()
        else:
            # trigram needs >=3 chars; short (often 2-char Chinese) queries scan with LIKE
            like = f"%{text}%"
            rows = conn.execute(
                "SELECT path, title, substr(body, max(1, instr(body, ?) - 20), 60) FROM notes "
                "WHERE body LIKE ? OR title LIKE ? LIMIT ?",
                (text, like, like, limit),
            ).fetchall()
    finally:
        conn.close()
    records = []
    for path, title, snippet in rows:
        parts = path.split("/")
        records.append({
            "title": title,
            "path": path,
            "snippet": (snippet or "").replace("\n", " ").strip(),
            "source": parts[1] if len(parts) > 2 else parts[0],
        })
    return {"records": records, "total": len(records), "index": stats}
