"""Note rollback execution (block #7, gated scope: proven on reversible paths).

Scope approved by JY: build and prove the rollback EXECUTION mechanism on
reversible targets (temp / _writeback_smoke) before touching real notes. The
notes table only kept previous/current hashes, not previous content, so a real
restore was impossible. This module backs up the previous content on write and
restores it on rollback, verifying the backup hash matches the expected
previous_hash first — so a rollback can never restore a wrong/corrupted version.
Idempotent: restoring twice yields the same content.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

BACKUP_SUFFIX = ".rollback.bak"


class RollbackError(RuntimeError):
    """Raised when a rollback cannot be safely executed."""


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8")) if path.exists() else "sha256:new-file"


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


def write_note_with_backup(path: str | Path, content: str) -> dict[str, Any]:
    """Write a note, backing up the previous content so rollback is possible."""
    target = Path(path)
    previous_hash = _hash_file(target)
    backup = _backup_path(target)
    had_previous = target.exists()
    if had_previous:
        shutil.copy2(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "path": str(target),
        "previous_hash": previous_hash,
        "current_hash": _hash_file(target),
        "backup_path": str(backup) if had_previous else None,
        "rollback_available": had_previous,
    }


def execute_rollback(
    path: str | Path,
    expected_previous_hash: str,
    *,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Restore the backed-up previous content, only if its hash matches expectation."""
    target = Path(path)
    backup = _backup_path(target)
    if not backup.exists():
        raise RollbackError("no rollback backup available for this note")
    backup_hash = _hash_file(backup)
    if backup_hash != expected_previous_hash:
        raise RollbackError(
            f"backup hash {backup_hash} does not match expected previous_hash {expected_previous_hash}"
        )
    pre_rollback_hash = _hash_file(target)
    shutil.copy2(backup, target)
    return {
        "restored": True,
        "path": str(target),
        "restored_hash": _hash_file(target),
        "pre_rollback_hash": pre_rollback_hash,
        "matched_previous_hash": True,
        "idempotency_key": idempotency_key,
    }
