"""Canonical source-to-note orchestrator (convergence step 1).

Unifies the previously-scattered pipeline into ONE product operation:

    fetch -> cost-cap preflight -> (dry-run preview | live) translate ->
    summarize -> value-signals -> vault write (with rollback backup)

This replaces ad-hoc call chains and the parallel dry-run write-preview path.
External effects (fetch / translate / summarize / write) are injected as
callables, so the orchestration — cost gate before any paid call, no-CC stop,
dry-run skips spend and write — is fully testable with stubs (no network/spend).
"""
from __future__ import annotations

from typing import Any, Callable

from loop_cost import CostCapExceeded, enforce_cost_cap, estimate_source_to_note_cost
from value_signals import build_value_signals

# fetch_fn(video_id) -> {"title","channel","en_text","zh_text","has_cc", ...}
FetchFn = Callable[[str], dict[str, Any]]
TranslateFn = Callable[[str], str]
SummarizeFn = Callable[[str, str, str], dict[str, Any]]
WriterFn = Callable[[str, dict[str, Any]], dict[str, Any]]


def run_source_to_note(
    *,
    video_id: str,
    url: str,
    per_job_cap_usd: float,
    fetch_fn: FetchFn,
    translator_fn: TranslateFn,
    summarizer_fn: SummarizeFn,
    writer_fn: WriterFn,
    dry_run: bool = True,
) -> dict[str, Any]:
    if not video_id:
        return {"ok": False, "stage": "extract", "reason": "invalid_url"}

    source = fetch_fn(video_id)
    en_text = str(source.get("en_text") or "")
    zh_cc = str(source.get("zh_text") or "")
    title = str(source.get("title") or video_id)
    if not source.get("has_cc") or not (en_text or zh_cc):
        return {
            "ok": False,
            "stage": "extract",
            "reason": "no_captions",
            "next_action": "operator_upload_for_asr",
            "title": title,
        }

    transcript_for_cost = en_text or zh_cc
    estimate = estimate_source_to_note_cost(len(transcript_for_cost))
    try:
        enforce_cost_cap(estimate, per_job_cap_usd)
    except CostCapExceeded as exc:
        return {
            "ok": False,
            "stage": "cost_preflight",
            "reason": "over_cost_cap",
            "blocked": str(exc),
            "estimate": estimate.as_dict(),
        }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "stage": "preview",
            "title": title,
            "estimate": estimate.as_dict(),
            "would_write": True,
            "provider_call_count": 0,
        }

    zh_text = translator_fn(en_text) if en_text else zh_cc
    summary = summarizer_fn(en_text or zh_cc, title, url)
    value_signals = build_value_signals(summary)
    write = writer_fn(
        video_id,
        {
            "url": url,
            "title": title,
            "channel": str(source.get("channel") or ""),
            "published": source.get("published"),
            "duration": source.get("duration"),
            "thumbnail": source.get("thumbnail"),
            "transcript_en": en_text,
            "transcript_zh": zh_text,
            "ai_summary": summary,
            "ai_mode": "quick",
            "manual_summary": "",
            "languages": source.get("languages") or ["en"],
            "save_mode": str(source.get("save_mode") or "create"),
            "is_short": bool(source.get("is_short")),
            "extraction_sources": ["youtube_native_caption"],
            "coverage_summary": "canonical source-to-note orchestrator",
        },
    )
    return {
        "ok": True,
        "dry_run": False,
        "stage": "written",
        "title": title,
        "estimate": estimate.as_dict(),
        "value_signals": value_signals,
        "write": write,
    }
