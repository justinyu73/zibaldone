"""Shared readiness helpers: app-state runtime access + local ASR runtime readiness."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app_state import AppStateError, AppStateRuntime


def _app_state(workspace_root: str, *, create: bool = False) -> AppStateRuntime:
    try:
        runtime = AppStateRuntime.open(workspace_root, create=create)
        if not create and not runtime.db_path.exists():
            raise AppStateError(f"workspace database does not exist: {runtime.db_path}")
        return runtime
    except AppStateError as exc:
        raise HTTPException(400, str(exc)) from exc


def _zero_trust_counters() -> dict[str, int]:
    return {
        "provider_call_count": 0,
        "media_download_count": 0,
        "credential_reads": 0,
        "source_note_writes": 0,
        "index_writes": 0,
        "queue_mutations": 0,
    }


def _asr_root() -> Path:
    # Standalone app: ASR (whisper.cpp) tooling lives under a configurable app dir,
    # not the old vaultwiki repo tree. Operator points YT_NOTE_ASR_ROOT at the build.
    return Path(os.getenv("YT_NOTE_ASR_ROOT", str(Path.home() / ".config" / "yt-note-app")))


def _path_status(path_text: str, root: Path) -> dict[str, Any]:
    path = Path(path_text)
    if not path.is_absolute():
        path = root / path
    exists = path.exists()
    return {
        "path": path.as_posix(),
        "exists": exists,
        "bytes": path.stat().st_size if exists and path.is_file() else 0,
    }


def _local_asr_runtime_readiness() -> dict[str, Any]:
    root = _asr_root()
    lock_path = root / "tools/whisper.cpp/runtime-lock.json"
    lock: dict[str, Any] = {}
    lock_error = ""
    if lock_path.exists():
        try:
            raw = json.loads(lock_path.read_text(encoding="utf-8"))
            lock = raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            lock_error = str(exc)

    build = lock.get("build") if isinstance(lock.get("build"), dict) else {}
    model = lock.get("model") if isinstance(lock.get("model"), dict) else {}
    binary_status = _path_status(str(build.get("binary_path") or "tools/whisper.cpp/bin/whisper-cli"), root)
    model_status = _path_status(str(model.get("path") or "tools/whisper.cpp/models/ggml-base.bin"), root)
    model_sha1_verified = model.get("official_sha1_verified") is True
    binary_ready = (
        build.get("build_ok") is True
        and binary_status["exists"]
        and binary_status["bytes"] == int(build.get("binary_bytes") or binary_status["bytes"] or 0)
    )
    model_ready = (
        model_sha1_verified
        and model_status["exists"]
        and model_status["bytes"] == int(model.get("bytes") or model_status["bytes"] or 0)
    )

    return {
        "ok": binary_ready and model_ready and not lock_error,
        "runtime_ready": binary_ready and model_ready and not lock_error,
        "runtime_name": lock.get("runtime_name") or "whisper.cpp",
        "runtime_version": lock.get("runtime_version") or "unknown",
        "model_name": str(model.get("path") or "ggml-base.bin").split("/")[-1],
        "runtime_lock_present": lock_path.exists(),
        "runtime_lock_path": lock_path.as_posix(),
        "runtime_lock_error": lock_error,
        "binary_ready": binary_ready,
        "binary": {
            **binary_status,
            "sha256": build.get("binary_sha256") or "",
            "help_exit_code": build.get("help_exit_code"),
        },
        "model_ready": model_ready,
        "model": {
            **model_status,
            "sha1": model.get("sha1") or "",
            "sha256": model.get("sha256") or "",
            "official_sha1_expected": model.get("official_sha1_expected") or "",
            "official_sha1_verified": model_sha1_verified,
        },
        "readiness_source": "tools/whisper.cpp/runtime-lock.json",
        "execution_mode": "readiness_only_no_asr_invocation",
        "asr_invoked": False,
        "media_downloaded": False,
        "credential_read": False,
        "source_note_written": False,
        "index_written": False,
        "scheduler_installed": False,
        "cloud_asr_fallback_used": False,
        "trust_counters": _zero_trust_counters(),
        "boundaries": [
            "read_only=true",
            "asr_invocation_allowed=false",
            "media_download_allowed=false",
            "cloud_asr_fallback_allowed=false",
            "credential_read_allowed=false",
            "source_note_write_allowed=false",
            "index_write_allowed=false",
            "scheduler_allowed=false",
        ],
    }
