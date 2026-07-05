"""Real-vault note write with rollback backup (block #1 + #2 pairing).

Promoting writes from the gitignored _writeback_smoke path to the real vault
(youtube dir) means future overwrites could lose content. This wraps the proven
save_learning_note so that, before overwriting an existing note, the current
file AND its index entry are backed up — making a consistent real-note rollback
(#7-live) possible. New notes (no existing index entry) are plain creates with
no backup needed. Preview-before-write stays the caller's responsibility.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from note_rollback import RollbackError, _backup_path, _hash_file, execute_rollback
from obsidian import load_index, save_learning_note, write_index

INDEX_ENTRY_BACKUP_SUFFIX = ".rollback.index.json"


def _index_entry_backup_path(note_abs: Path) -> Path:
    return note_abs.with_name(note_abs.name + INDEX_ENTRY_BACKUP_SUFFIX)


def vault_write_with_rollback(
    *,
    vault_path: str,
    subfolder: str,
    video_id: str,
    save_kwargs: dict[str, Any],
) -> dict[str, Any]:
    index = load_index(vault_path, subfolder)
    existing = index.get("items", {}).get(video_id)
    backup_info = None
    if existing and existing.get("note_path"):
        note_abs = Path(vault_path) / str(existing["note_path"])
        if note_abs.exists():
            backup = _backup_path(note_abs)
            shutil.copy2(note_abs, backup)
            entry_backup = _index_entry_backup_path(note_abs)
            entry_backup.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
            backup_info = {
                "backup_path": str(backup),
                "previous_hash": _hash_file(note_abs),
                "index_entry_backup": str(entry_backup),
            }
    result = save_learning_note(
        vault_path=vault_path,
        subfolder=subfolder,
        video_id=video_id,
        **save_kwargs,
    )
    result["backup"] = backup_info
    result["rollback_available"] = backup_info is not None
    return result


def vault_rollback(
    *,
    vault_path: str,
    subfolder: str,
    video_id: str,
    expected_previous_hash: str,
) -> dict[str, Any]:
    """Roll back both the note file AND its index entry to the backed-up version."""
    index = load_index(vault_path, subfolder)
    existing = index.get("items", {}).get(video_id)
    if not existing or not existing.get("note_path"):
        raise RollbackError(f"no index entry to roll back for video {video_id}")
    note_abs = Path(vault_path) / str(existing["note_path"])
    rollback = execute_rollback(note_abs, expected_previous_hash)  # verifies hash, restores file
    entry_backup = _index_entry_backup_path(note_abs)
    index_entry_restored = False
    if entry_backup.exists():
        previous_entry = json.loads(entry_backup.read_text(encoding="utf-8"))
        index["items"][video_id] = previous_entry
        write_index(vault_path, subfolder, index)
        index_entry_restored = True
    rollback["index_entry_restored"] = index_entry_restored
    return rollback
