"""Readiness routes: health, app-state runtime, and caption/ASR readiness probes."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app_state import AppStateError, AppStateRuntime, stable_id
from model_policy import load_model_policy
from production_extractor import tooling_status as production_extractor_tooling_status
from provider_runtime import runtime_status as provider_runtime_status
from schemas import (
    AppCaptionProbeReq,
    AppLocalAsrReportOnlyProbeReq,
    AppNativeCaptionApiProbeReq,
    AppStorageTargetReq,
    AppYtdlpSubtitleFallbackProbeReq,
)
from services.readiness import (
    _app_state,
    _asr_root,
    _local_asr_runtime_readiness,
    _zero_trust_counters,
)
from transcript import (
    extract_video_id,
    fetch_native_caption_api_only,
    fetch_ytdlp_subtitle_fallback_only,
)

router = APIRouter()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_command(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def _command_error(completed: subprocess.CompletedProcess[str]) -> str:
    return (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()[-1600:]


def _resolve_yt_dlp_binary() -> str:
    override = os.getenv("YT_DLP_BINARY", "").strip()
    if override:
        return override
    return shutil.which("yt-dlp") or ""


def _blocked_intake(error_code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": error_code,
        "message": message,
        "trust_counters": _zero_trust_counters(),
    }


def _blocked_native_caption_probe(error_code: str, message: str, route_state: str = "blocked_or_retry_later") -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": error_code,
        "message": message,
        "route_state": route_state,
        "yt_dlp_fallback_used": False,
        "media_downloaded": False,
        "credential_read": False,
        "persisted": False,
        "trust_counters": _zero_trust_counters(),
    }


def _blocked_ytdlp_subtitle_fallback_probe(
    error_code: str,
    message: str,
    route_state: str = "ytdlp_subtitle_fallback_blocked_or_retry_later",
) -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": error_code,
        "message": message,
        "route_state": route_state,
        "yt_dlp_fallback_used": False,
        "media_downloaded": False,
        "credential_read": False,
        "persisted": False,
        "trust_counters": _zero_trust_counters(),
    }


def _blocked_local_asr_report_only_probe(
    error_code: str,
    message: str,
    route_state: str = "local_asr_report_only_blocked_or_retry_later",
) -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": error_code,
        "message": message,
        "route_state": route_state,
        "report_only": True,
        "media_downloaded": False,
        "asr_invoked": False,
        "credential_read": False,
        "persisted": False,
        "cloud_asr_fallback_used": False,
        "source_note_written": False,
        "index_written": False,
        "scheduler_installed": False,
        "trust_counters": _zero_trust_counters(),
        "asr_invocation_count": 0,
    }


def _local_asr_report_only_probe(
    *,
    video_id: str,
    source_id: str,
    canonical_url: str,
    max_sample_seconds: int,
    max_download_bytes: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    root = _asr_root()
    readiness = _local_asr_runtime_readiness()
    if readiness.get("runtime_ready") is not True:
        return {
            **_blocked_local_asr_report_only_probe(
                "local_asr_runtime_not_ready",
                "local ASR runtime is not ready",
            ),
            "source_id": source_id,
            "local_asr_runtime_readiness": readiness,
        }

    capped_seconds = min(max(1, int(max_sample_seconds or 30)), 30)
    capped_bytes = min(max(1_000_000, int(max_download_bytes or 10_000_000)), 10_000_000)
    yt_dlp = _resolve_yt_dlp_binary()
    ffmpeg = shutil.which("ffmpeg") or ""
    whisper = Path(str(readiness.get("binary", {}).get("path") or root / "tools/whisper.cpp/bin/whisper-cli"))
    model = Path(str(readiness.get("model", {}).get("path") or root / "tools/whisper.cpp/models/ggml-tiny.en.bin"))
    if not yt_dlp:
        return _blocked_local_asr_report_only_probe("yt_dlp_binary_unavailable", "yt-dlp binary is not available")
    if not ffmpeg:
        return _blocked_local_asr_report_only_probe("ffmpeg_unavailable", "ffmpeg is not available")
    if not whisper.exists() or not model.exists():
        return _blocked_local_asr_report_only_probe("local_asr_runtime_not_ready", "whisper.cpp binary or model is missing")

    tmp_root = Path(tempfile.mkdtemp(prefix=f"vaultwiki_video_intake_local_asr_{video_id}_", dir="/tmp"))
    sample_path = tmp_root / "local_asr_sample.wav"
    output_prefix = tmp_root / "local_asr_report"
    errors: list[str] = []
    metadata: dict[str, Any] = {}
    media_sample: dict[str, Any] = {}
    asr_report: dict[str, Any] = {}
    cleanup_verified = False

    try:
        metadata_completed = _run_command(
            [
                yt_dlp,
                "--ignore-config",
                "--no-cache-dir",
                "--no-playlist",
                "--skip-download",
                "--dump-json",
                "--no-warnings",
                canonical_url,
            ],
            timeout=120,
        )
        if metadata_completed.returncode != 0:
            errors.append(f"metadata_failed: {_command_error(metadata_completed)}")
        else:
            raw_metadata = json.loads(metadata_completed.stdout or "{}")
            metadata = {
                "id": raw_metadata.get("id", ""),
                "title_present": bool(raw_metadata.get("title")),
                "duration_seconds": float(raw_metadata.get("duration") or 0),
                "extractor": raw_metadata.get("extractor", ""),
                "availability": raw_metadata.get("availability", ""),
            }
            if metadata.get("id") != video_id:
                errors.append(f"metadata_id_mismatch: {metadata.get('id')}")

        stream_url = ""
        if not errors:
            stream_completed = _run_command(
                [
                    yt_dlp,
                    "--ignore-config",
                    "--no-cache-dir",
                    "--no-playlist",
                    "--no-warnings",
                    "-f",
                    "bestaudio[ext=m4a]/bestaudio/best",
                    "-g",
                    canonical_url,
                ],
                timeout=120,
            )
            if stream_completed.returncode != 0:
                errors.append(f"stream_url_failed: {_command_error(stream_completed)}")
            else:
                stream_url = next((line.strip() for line in stream_completed.stdout.splitlines() if line.strip()), "")
                if not stream_url:
                    errors.append("stream_url_empty")

        if not errors:
            audio_completed = _run_command(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-t",
                    str(capped_seconds),
                    "-i",
                    stream_url,
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-f",
                    "wav",
                    sample_path.as_posix(),
                ],
                timeout=180,
            )
            if audio_completed.returncode != 0:
                errors.append(f"ffmpeg_sample_failed: {_command_error(audio_completed)}")
            elif not sample_path.exists():
                errors.append("sample_file_missing_after_ffmpeg")
            else:
                sample_bytes = sample_path.stat().st_size
                if sample_bytes > capped_bytes:
                    errors.append(f"sample_exceeds_max_bytes: {sample_bytes}")
                media_sample = {
                    "bytes": sample_bytes,
                    "sha256": _sha256_file(sample_path),
                    "max_sample_seconds": capped_seconds,
                    "max_download_bytes": capped_bytes,
                    "container": "wav",
                    "audio_channels": 1,
                    "audio_sample_rate": 16000,
                    "temp_path_redacted": True,
                }

        if not errors:
            asr_completed = _run_command(
                [
                    whisper.as_posix(),
                    "-m",
                    model.as_posix(),
                    "-f",
                    sample_path.as_posix(),
                    "-l",
                    "en",
                    "-otxt",
                    "-of",
                    output_prefix.as_posix(),
                ],
                timeout=180,
            )
            output_path = output_prefix.with_suffix(".txt")
            transcript_preview = output_path.read_text(encoding="utf-8", errors="replace").strip() if output_path.exists() else ""
            asr_report = {
                "asr_ok": asr_completed.returncode == 0 and bool(transcript_preview),
                "asr_exit_code": asr_completed.returncode,
                "transcript_preview": transcript_preview[:2000],
                "transcript_preview_chars": len(transcript_preview[:2000]),
                "transcript_truncated": len(transcript_preview) > 2000,
                "language": "en",
                "model_name": readiness.get("model_name") or "ggml-tiny.en.bin",
                "runtime_name": readiness.get("runtime_name") or "whisper.cpp",
                "runtime_version": readiness.get("runtime_version") or "unknown",
            }
            if not asr_report["asr_ok"]:
                errors.append(f"local_asr_failed: {_command_error(asr_completed)}")
    except (json.JSONDecodeError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        errors.append(f"runtime_error: {exc}")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
        cleanup_verified = not tmp_root.exists()

    ok = not errors and bool(media_sample) and asr_report.get("asr_ok") is True and cleanup_verified
    trust_counters = {
        **_zero_trust_counters(),
        "media_download_count": 1 if media_sample else 0,
    }
    return {
        "ok": ok,
        "source_id": source_id,
        "canonical_id": video_id,
        "canonical_url": canonical_url,
        "route_state": "local_asr_report_only_complete" if ok else "local_asr_report_only_failed",
        "report_only": True,
        "execution_mode": "bounded_temp_media_local_asr_report_only",
        "local_asr_runtime_readiness": readiness,
        "metadata": metadata,
        "media_sample": media_sample,
        "asr_report": asr_report,
        "errors": errors,
        "media_downloaded": bool(media_sample),
        "asr_invoked": bool(asr_report),
        "credential_read": False,
        "persisted": False,
        "cloud_asr_fallback_used": False,
        "source_note_written": False,
        "index_written": False,
        "scheduler_installed": False,
        "trust_counters": trust_counters,
        "asr_invocation_count": 1 if asr_report else 0,
        "cleanup_verified": cleanup_verified,
        "caps": {
            "max_sample_seconds": capped_seconds,
            "max_download_bytes": capped_bytes,
            "temp_storage": "/tmp",
            "cleanup_policy": "delete_temp_media_and_asr_output_after_report",
        },
        "runtime_ms": round((time.perf_counter() - started) * 1000),
        "boundaries": [
            "report_only=true",
            "credential_read=false",
            "cloud_asr_fallback=false",
            "source_note_write=false",
            "index_write=false",
            "scheduler=false",
            "cleanup_verified=true" if cleanup_verified else "cleanup_verified=false",
        ],
    }


@router.get("/api/health")
def health():
    return {
        "ok": True,
        "vault_configured": bool(os.getenv("OBSIDIAN_VAULT_PATH")),
        "translate_configured": bool(os.getenv("OPENAI_API_KEY")),
        "model_policy": load_model_policy(),
        "provider_runtime": provider_runtime_status(),
        "production_extractor": production_extractor_tooling_status(),
    }


@router.get("/api/app/health")
def app_state_health(workspace_root: str = ""):
    if not workspace_root:
        return {
            "ok": True,
            "runtime": "video_intake_app_local_state",
            "workspace_configured": False,
            "provider_call_count": 0,
            "media_download_count": 0,
            "credential_reads": 0,
            "source_note_writes": 0,
            "index_writes": 0,
            "queue_mutations": 0,
            "scheduler_installed": False,
        }
    return _app_state(workspace_root).health()


@router.get("/api/app/local-asr-runtime/readiness")
def app_local_asr_runtime_readiness():
    return _local_asr_runtime_readiness()


@router.get("/api/app/retained-artifacts")
def app_state_retained_artifacts(workspace_root: str):
    try:
        return _app_state(workspace_root).retained_artifact_read_model()
    except AppStateError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/app/storage-targets")
def app_state_create_storage_target(req: AppStorageTargetReq):
    try:
        target = _app_state(req.workspace_root).create_storage_target(
            workspace_id=req.workspace_id,
            root_path=req.root_path,
            adapter_type=req.adapter_type,
            permissions=req.permissions,
            write_mode=req.write_mode,
        )
        return {"storage_target": target}
    except AppStateError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/app/caption-probe")
def app_state_caption_probe(req: AppCaptionProbeReq):
    if not req.workspace_root.strip():
        return _blocked_intake("workspace_required", "workspace_root is required")
    if not req.workspace_id.strip():
        return _blocked_intake("workspace_required", "workspace_id is required")
    if not req.source_id.strip():
        return _blocked_intake("source_required", "source_id is required")
    if req.platform.strip().lower() != "youtube":
        return _blocked_intake("unsupported_platform", "caption probe currently supports youtube only")
    if not req.dry_run:
        return _blocked_intake("gate_required", "dry_run=false requires a separate execution gate")

    try:
        AppStateRuntime.open(req.workspace_root, create=False)
    except AppStateError as exc:
        return _blocked_intake("workspace_required", str(exc))

    video_id = req.canonical_id.strip() or extract_video_id(req.canonical_url)
    if not video_id:
        return _blocked_intake("intake_not_ready", "canonical_id or canonical_url from URL intake is required")

    expected_source_id = stable_id("src", "youtube", video_id)
    if req.source_id != expected_source_id:
        return _blocked_intake("intake_not_ready", "source_id does not match canonical YouTube id")

    source_id = req.source_id.strip()
    route_preference = req.route_preference.strip() or "native_caption_first"
    idempotency_key = req.idempotency_key.strip() or f"caption-probe:{source_id}:{route_preference}:v1"
    job_id = stable_id("job", idempotency_key, "caption_probe", "native_caption_probe_pending")

    return {
        "ok": True,
        "dry_run": True,
        "source_id": source_id,
        "job": {
            "job_id": job_id,
            "source_id": source_id,
            "stage": "caption_probe",
            "status": "caption_probe_ready",
            "route_state": "native_caption_probe_pending",
            "progress": 0,
            "idempotency_key": idempotency_key,
        },
        "caption_probe_plan": {
            "probe_order": ["native_caption_api", "yt_dlp_subtitle_fallback"],
            "caption_languages": req.caption_languages,
            "execute_native_caption_api": False,
            "execute_yt_dlp_fallback": False,
            "persist_evidence": False,
        },
        "evidence_readiness": {
            "native_caption_probe_allowed": True,
            "caption_segments_would_be_reviewable": True,
            "asr_allowed": False,
            "ocr_allowed": False,
            "provider_allowed": False,
            "media_download_allowed": False,
            "write_allowed": False,
        },
        "trust_counters": _zero_trust_counters(),
        "next_gate": "video-intake-app-tauri-caption-probe-contract-execution-gate",
    }


@router.post("/api/app/native-caption-api-probe")
def app_state_native_caption_api_probe(req: AppNativeCaptionApiProbeReq):
    if not req.workspace_root.strip():
        return _blocked_native_caption_probe("workspace_required", "workspace_root is required")
    if not req.workspace_id.strip():
        return _blocked_native_caption_probe("workspace_required", "workspace_id is required")
    if not req.source_id.strip():
        return _blocked_native_caption_probe("source_required", "source_id is required")
    if req.platform.strip().lower() != "youtube":
        return _blocked_native_caption_probe("unsupported_platform", "native caption API probe currently supports youtube only")
    if req.allow_ytdlp_fallback:
        return _blocked_native_caption_probe("ytdlp_fallback_blocked", "yt-dlp fallback requires a separate execution gate")
    if req.allow_media_download:
        return _blocked_native_caption_probe("media_download_blocked", "media download requires a separate execution gate")
    if req.allow_credential_read:
        return _blocked_native_caption_probe("credential_blocked", "credential or cookie read requires a separate execution gate")
    if req.persist_evidence:
        return _blocked_native_caption_probe("gate_required", "persist_evidence=true requires a separate SQLite mutation gate")

    try:
        AppStateRuntime.open(req.workspace_root, create=False)
    except AppStateError as exc:
        return _blocked_native_caption_probe("workspace_required", str(exc))

    video_id = req.canonical_id.strip() or extract_video_id(req.canonical_url)
    if not video_id:
        return _blocked_native_caption_probe("source_required", "canonical_id or canonical_url from caption probe is required")

    expected_source_id = stable_id("src", "youtube", video_id)
    if req.source_id != expected_source_id:
        return _blocked_native_caption_probe("source_required", "source_id does not match canonical YouTube id")

    source_id = req.source_id.strip()
    idempotency_key = req.idempotency_key.strip() or f"native-caption-api-probe:{source_id}:v1"
    job_id = stable_id("job", idempotency_key, "native_caption_api_probe", "single_source")
    probe = fetch_native_caption_api_only(video_id, req.caption_languages)

    if not probe.get("ok"):
        return {
            **_blocked_native_caption_probe(
                probe.get("error_code") or "native_caption_unavailable",
                probe.get("message") or "來源沒有可審查的字幕",
                probe.get("route_state") or "native_caption_unavailable",
            ),
            "source_id": source_id,
            "native_caption_probe": probe,
        }

    return {
        "ok": True,
        "source_id": source_id,
        "job": {
            "job_id": job_id,
            "source_id": source_id,
            "stage": "native_caption_api_probe",
            "status": "native_caption_api_probe_complete",
            "route_state": "native_caption_available",
            "progress": 100,
            "idempotency_key": idempotency_key,
        },
        "native_caption_probe": probe,
        "evidence_readiness": {
            "native_caption_segments_reviewable": True,
            "asr_allowed": False,
            "ocr_allowed": False,
            "provider_allowed": False,
            "media_download_allowed": False,
            "write_allowed": False,
        },
        "trust_counters": _zero_trust_counters(),
        "next_gate": "video-intake-app-tauri-native-caption-api-probe-execution-gate",
    }


@router.post("/api/app/ytdlp-subtitle-fallback-probe")
def app_state_ytdlp_subtitle_fallback_probe(req: AppYtdlpSubtitleFallbackProbeReq):
    if not req.workspace_root.strip():
        return _blocked_ytdlp_subtitle_fallback_probe("workspace_required", "workspace_root is required")
    if not req.workspace_id.strip():
        return _blocked_ytdlp_subtitle_fallback_probe("workspace_required", "workspace_id is required")
    if not req.source_id.strip():
        return _blocked_ytdlp_subtitle_fallback_probe("source_required", "source_id is required")
    if req.platform.strip().lower() != "youtube":
        return _blocked_ytdlp_subtitle_fallback_probe("unsupported_platform", "yt-dlp subtitle fallback currently supports youtube only")
    if req.triggering_operator_state.strip() != "native_caption_unavailable_review_required":
        return _blocked_ytdlp_subtitle_fallback_probe(
            "operator_state_required",
            "yt-dlp subtitle fallback requires native_caption_unavailable_review_required",
        )
    if not req.allow_ytdlp_subtitle_fallback:
        return _blocked_ytdlp_subtitle_fallback_probe("gate_required", "allow_ytdlp_subtitle_fallback=true is required for this execution gate")
    if req.allow_media_download:
        return _blocked_ytdlp_subtitle_fallback_probe("media_download_blocked", "media download requires a separate execution gate")
    if req.allow_credential_read:
        return _blocked_ytdlp_subtitle_fallback_probe("credential_blocked", "credential or cookie read requires a separate execution gate")
    if req.persist_evidence:
        return _blocked_ytdlp_subtitle_fallback_probe("gate_required", "persist_evidence=true requires a separate SQLite mutation gate")

    try:
        AppStateRuntime.open(req.workspace_root, create=False)
    except AppStateError as exc:
        return _blocked_ytdlp_subtitle_fallback_probe("workspace_required", str(exc))

    video_id = req.canonical_id.strip() or extract_video_id(req.canonical_url)
    if not video_id:
        return _blocked_ytdlp_subtitle_fallback_probe("source_required", "canonical_id or canonical_url from native caption probe is required")

    expected_source_id = stable_id("src", "youtube", video_id)
    if req.source_id != expected_source_id:
        return _blocked_ytdlp_subtitle_fallback_probe("source_required", "source_id does not match canonical YouTube id")

    source_id = req.source_id.strip()
    idempotency_key = req.idempotency_key.strip() or f"ytdlp-subtitle-fallback-probe:{source_id}:v1"
    job_id = stable_id("job", idempotency_key, "ytdlp_subtitle_fallback_probe", "single_source")
    probe = fetch_ytdlp_subtitle_fallback_only(video_id, req.caption_languages)

    if not probe.get("ok"):
        return {
            "ok": False,
            "source_id": source_id,
            "error_code": probe.get("error_code") or "ytdlp_subtitle_unavailable",
            "message": probe.get("message") or "備援工具未取得可審查的字幕軌",
            "route_state": probe.get("route_state") or "ytdlp_subtitle_unavailable_review_required",
            "yt_dlp_fallback_used": bool(probe.get("yt_dlp_fallback_used")),
            "media_downloaded": False,
            "credential_read": False,
            "persisted": False,
            "ytdlp_subtitle_probe": probe,
            "available_actions": [
                "mark_unavailable",
                "manual_evidence_placeholder",
                "defer_to_asr_ocr_gate",
            ],
            "trust_counters": _zero_trust_counters(),
            "next_gate": "video-intake-app-tauri-ytdlp-subtitle-fallback-execution-gate",
        }

    return {
        "ok": True,
        "source_id": source_id,
        "job": {
            "job_id": job_id,
            "source_id": source_id,
            "stage": "ytdlp_subtitle_fallback_probe",
            "status": "ytdlp_subtitle_fallback_complete",
            "route_state": "ytdlp_subtitle_segments_reviewable",
            "progress": 100,
            "idempotency_key": idempotency_key,
        },
        "ytdlp_subtitle_probe": probe,
        "evidence_readiness": {
            "subtitle_segments_reviewable": True,
            "asr_allowed": False,
            "ocr_allowed": False,
            "provider_allowed": False,
            "media_download_allowed": False,
            "write_allowed": False,
        },
        "trust_counters": _zero_trust_counters(),
        "next_gate": "video-intake-app-tauri-ytdlp-subtitle-fallback-execution-gate",
    }


@router.post("/api/app/local-asr-report-only-probe")
def app_state_local_asr_report_only_probe(req: AppLocalAsrReportOnlyProbeReq):
    if not req.workspace_root.strip():
        return _blocked_local_asr_report_only_probe("workspace_required", "workspace_root is required")
    if not req.workspace_id.strip():
        return _blocked_local_asr_report_only_probe("workspace_required", "workspace_id is required")
    if not req.source_id.strip():
        return _blocked_local_asr_report_only_probe("source_required", "source_id is required")
    if req.platform.strip().lower() != "youtube":
        return _blocked_local_asr_report_only_probe("unsupported_platform", "local ASR report-only probe currently supports youtube only")
    if req.triggering_operator_state.strip() != "ytdlp_subtitle_unavailable_review_required":
        return _blocked_local_asr_report_only_probe(
            "operator_state_required",
            "local ASR report-only probe requires ytdlp_subtitle_unavailable_review_required",
        )
    if not req.allow_media_download:
        return _blocked_local_asr_report_only_probe("gate_required", "allow_media_download=true is required for this approved action")
    if not req.allow_local_asr:
        return _blocked_local_asr_report_only_probe("gate_required", "allow_local_asr=true is required for this approved action")
    if req.allow_credential_read:
        return _blocked_local_asr_report_only_probe("credential_blocked", "credential or cookie read is not allowed for this action")
    if req.persist_evidence:
        return _blocked_local_asr_report_only_probe("gate_required", "persist_evidence=true requires a separate write gate")

    try:
        AppStateRuntime.open(req.workspace_root, create=False)
    except AppStateError as exc:
        return _blocked_local_asr_report_only_probe("workspace_required", str(exc))

    video_id = req.canonical_id.strip() or extract_video_id(req.canonical_url)
    if not video_id:
        return _blocked_local_asr_report_only_probe("source_required", "canonical_id or canonical_url from unavailable subtitle state is required")

    expected_source_id = stable_id("src", "youtube", video_id)
    if req.source_id != expected_source_id:
        return _blocked_local_asr_report_only_probe("source_required", "source_id does not match canonical YouTube id")

    source_id = req.source_id.strip()
    idempotency_key = req.idempotency_key.strip() or f"local-asr-report-only:{source_id}:v1"
    job_id = stable_id("job", idempotency_key, "local_asr_report_only_probe", "single_source")
    canonical_url = req.canonical_url.strip() or f"https://www.youtube.com/watch?v={video_id}"
    probe = _local_asr_report_only_probe(
        video_id=video_id,
        source_id=source_id,
        canonical_url=canonical_url,
        max_sample_seconds=req.max_sample_seconds,
        max_download_bytes=req.max_download_bytes,
    )
    return {
        **probe,
        "job": {
            "job_id": job_id,
            "source_id": source_id,
            "stage": "local_asr_report_only_probe",
            "status": "local_asr_report_only_complete" if probe.get("ok") else "local_asr_report_only_failed",
            "route_state": probe.get("route_state") or "local_asr_report_only_failed",
            "progress": 100 if probe.get("ok") else 0,
            "idempotency_key": idempotency_key,
        },
        "next_gate": "video-intake-app-local-asr-report-only-action-ui-human-confirmation-gate",
    }
