"""Value-signal quality layer for produced summaries (block #6).

The summary pipeline already emits topic / key_points / terms / content_value /
platform / category as a flat string dict. This layer turns that into a typed,
quality-assessed value-signal read model: it splits multi-line fields into
lists, flags an auto-filled (not human-validated) content_value, scores
completeness, and surfaces review warnings. Pure functions — no provider call.
"""
from __future__ import annotations

from typing import Any

SIGNAL_FIELDS = (
    "explicit_topic",
    "key_points",
    "terms",
    "content_value",
    "source_platform",
    "content_category",
)
# Prefix written by _normalize_summary when content_value was auto-derived.
AUTO_CONTENT_VALUE_PREFIX = "可先對應到本機影片筆記 APP"
MAX_KEY_POINTS = 3


def _lines(value: Any) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def build_value_signals(summary: dict[str, Any]) -> dict[str, Any]:
    topic = str(summary.get("explicit_topic", "")).strip()
    key_points = _lines(summary.get("key_points"))
    terms = _lines(summary.get("terms"))
    content_value = str(summary.get("content_value", "")).strip()
    platform = str(summary.get("source_platform", "")).strip()
    category = str(summary.get("content_category", "")).strip()

    content_value_is_auto = content_value.startswith(AUTO_CONTENT_VALUE_PREFIX)
    fields_present = {field: bool(str(summary.get(field, "")).strip()) for field in SIGNAL_FIELDS}
    completeness = round(sum(fields_present.values()) / len(SIGNAL_FIELDS), 3)

    warnings: list[str] = []
    if not topic:
        warnings.append("missing_topic")
    if not key_points:
        warnings.append("missing_key_points")
    elif len(key_points) > MAX_KEY_POINTS:
        warnings.append("too_many_key_points")
    if not content_value or content_value_is_auto:
        warnings.append("content_value_not_human_validated")
    if not category:
        warnings.append("missing_category")

    return {
        "schema_id": "yt-value-signals-v1",
        "topic": topic,
        "key_points": key_points,
        "key_point_count": len(key_points),
        "terms": terms,
        "term_count": len(terms),
        "content_value": content_value,
        "content_value_is_auto_placeholder": content_value_is_auto,
        "platform": platform,
        "category": category,
        "quality": {
            "completeness": completeness,
            "fields_present": fields_present,
            "warnings": warnings,
            "review_recommended": bool(warnings),
        },
    }
