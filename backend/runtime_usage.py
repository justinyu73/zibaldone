"""Repo-local runtime usage logging for YT transcript tooling.

This module records safe usage metadata only. It never stores API keys, prompt
text, transcript text, media bytes, images, or provider payloads.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = 1


def _app_data_dir() -> Path:
    # Standalone app: usage log lives with keys/settings under the user config dir,
    # never the old vaultwiki repo tree (which also breaks when frozen, cwd='/').
    return Path(os.getenv("YT_NOTE_APP_CONFIG_DIR", str(Path.home() / ".config" / "yt-note-app")))


def default_usage_log_path() -> Path:
    configured = os.getenv("VAULTWIKI_RUNTIME_USAGE_LOG", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else _app_data_dir() / path
    return _app_data_dir() / "runtime_usage_events.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def usage_from_response(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return {"confidence": "not_available"}

    def get_value(*names: str) -> int | None:
        for name in names:
            if isinstance(usage, dict):
                value = usage.get(name)
            else:
                value = getattr(usage, name, None)
            parsed = _read_int(value)
            if parsed is not None:
                return parsed
        return None

    input_tokens = get_value("input_tokens", "prompt_tokens")
    output_tokens = get_value("output_tokens", "completion_tokens")
    total_tokens = get_value("total_tokens")
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return {"confidence": "not_available"}
    return {
        "confidence": "exact",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def usage_from_estimate(estimate: dict[str, Any]) -> dict[str, Any]:
    input_tokens = _read_int(estimate.get("input_tokens"))
    output_tokens = _read_int(estimate.get("output_tokens"))
    total_tokens = _read_int(estimate.get("estimated_tokens"))
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
    return {
        "confidence": "estimated",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_usd": estimate.get("estimated_usd"),
    }


def append_runtime_usage_event(
    *,
    task: str,
    provider: str,
    model: str,
    mode: str,
    endpoint: str,
    usage: dict[str, Any],
    provider_call_count: int = 0,
    raw_evidence_ref: str = "",
    decision_scope: str = "",
    log_path: Path | None = None,
) -> dict[str, Any]:
    path = log_path or default_usage_log_path()
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"runtime-usage-{uuid4().hex[:12]}",
        "observed_at": now_iso(),
        "source_runtime": "pj_yt_transcript",
        "source_scope": "repo_local_runtime_event",
        "privacy_boundary": "safe_repo_local_no_prompt_or_media",
        "upload_policy": "no_upload",
        "task": task,
        "provider": provider,
        "model": model,
        "mode": mode,
        "endpoint": endpoint,
        "usage": usage,
        "provider_call_count": provider_call_count,
        "raw_evidence_ref": raw_evidence_ref or "runtime:response_metadata_only",
        "decision_scope": decision_scope or "usage accounting only; not product pass evidence",
        "forbidden_fields": ["api_key", "prompt_text", "transcript_text", "media_base64", "image_base64"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event
