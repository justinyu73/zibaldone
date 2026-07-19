"""Real-vault news note write with rollback backup (news source lane).

Parallel to `vault_write` (the caption-pipeline writer): keyed by a URL-derived
`source_hash` instead of a video id, with its own news index (`_news_index.json`)
and subfolder. Reuses the proven `write_note_with_backup` so overwriting an
existing news note stays reversible. The orchestrator renders the markdown; this
module only persists it and maintains the index.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from note_rollback import write_note_with_backup
from obsidian import now_stamp, slugify

NEWS_INDEX_NAME = "_news_index.json"


def news_root(vault_path: str, subfolder: str) -> Path:
    vault = Path(vault_path).expanduser().resolve()
    if not vault.exists():
        raise FileNotFoundError(f"Vault path does not exist: {vault}")
    if not vault.is_dir():
        raise NotADirectoryError(f"Vault path is not a directory: {vault}")
    root = vault / subfolder if subfolder else vault
    root.mkdir(parents=True, exist_ok=True)
    return root


def _index_path(vault_path: str, subfolder: str) -> Path:
    return news_root(vault_path, subfolder) / NEWS_INDEX_NAME


def load_news_index(vault_path: str, subfolder: str) -> dict[str, Any]:
    path = _index_path(vault_path, subfolder)
    if not path.exists():
        return {"version": 1, "updated": now_stamp(), "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "updated": now_stamp(), "items": {}}
    if not isinstance(data.get("items"), dict):
        data["items"] = {}
    return data


def write_news_index(vault_path: str, subfolder: str, data: dict[str, Any]) -> None:
    import os

    data["version"] = 1
    data["updated"] = now_stamp()
    path = _index_path(vault_path, subfolder)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_news_note(
    *,
    vault_path: str,
    subfolder: str,
    source_hash: str,
    url: str,
    title: str,
    note_markdown: str,
) -> dict[str, Any]:
    """Persist a rendered news note, keyed by source_hash. Re-intaking the same
    URL updates the existing note (reversible via the backup) instead of forking."""
    root = news_root(vault_path, subfolder)
    index = load_news_index(vault_path, subfolder)
    existing = index.get("items", {}).get(source_hash)
    if existing and existing.get("note_path"):
        note_abs = Path(vault_path).expanduser().resolve() / str(existing["note_path"])
        created_new = not note_abs.exists()
    else:
        note_abs = root / f"{slugify(title)}_news_{source_hash}.md"
        created_new = True
    write = write_note_with_backup(note_abs, note_markdown)
    relative_path = str(note_abs.relative_to(Path(vault_path).expanduser().resolve()))
    index.setdefault("items", {})[source_hash] = {
        "note_path": relative_path,
        "url": url,
        "title": title,
        "source_hash": source_hash,
        "updated": now_stamp(),
    }
    write_news_index(vault_path, subfolder, index)
    return {
        "relative_path": relative_path,
        "created_new": created_new,
        "rollback_available": write.get("rollback_available", False),
        "previous_hash": write.get("previous_hash"),
        "current_hash": write.get("current_hash"),
    }
