"""Shared library/media/summary logic used by routers.library and main (meeting/capture)."""
from __future__ import annotations

import math
import os
import re
from typing import Any

import app_config
from model_policy import model_for_task


_AUDIO_MIME_BY_EXT = {
    ".mp3": "audio/mpeg", ".m4a": "audio/m4a", ".mp4": "video/mp4",
    ".wav": "audio/wav", ".webm": "audio/webm", ".ogg": "audio/ogg",
}


def _settings() -> tuple[str, str]:
    return (
        os.getenv("OBSIDIAN_VAULT_PATH", "").strip(),
        os.getenv("OBSIDIAN_SUBFOLDER", "note_study/02_Sources/youtube").strip(),
    )


def _estimate(text: str, mode: str) -> dict[str, Any]:
    input_tokens = max(1, math.ceil(len(text) / 4))
    output_factor = 0.18 if mode == "quick" else 0.45
    output_tokens = max(160, math.ceil(input_tokens * output_factor))
    model = model_for_task("summary", "gpt-5.2")
    input_price, output_price = app_config.price_for_model(model)
    cost = (input_tokens / 1_000_000 * input_price) + (output_tokens / 1_000_000 * output_price)
    return {
        "model": model,
        "mode": mode,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_tokens": input_tokens + output_tokens,
        "estimated_usd": round(cost, 6),
    }


def _format_summary_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (_format_summary_value(item) for item in value)))
    if isinstance(value, dict):
        return "\n".join(filter(None, (_format_summary_value(item) for item in value.values())))
    return str(value)


_OPENCC_CONVERTER = None


def _to_traditional_text(value: str) -> str:
    """Simplified → Taiwan Traditional via OpenCC s2twp (full coverage + Taiwan
    phrasing; replaces the old 57-entry hand-rolled table)."""
    global _OPENCC_CONVERTER
    if _OPENCC_CONVERTER is None:
        from opencc import OpenCC

        _OPENCC_CONVERTER = OpenCC("s2twp")
    return _OPENCC_CONVERTER.convert(value or "")


SUMMARY_ALIASES: dict[str, tuple[str, ...]] = {
    "explicit_topic": (
        "explicitTopic",
        "topic",
        "title_topic",
        "明確主題",
        "影片明確主題",
        "主題",
    ),
    "key_points": (
        "keyPoints",
        "points",
        "summary_points",
        "摘要",
        "重點",
        "重點條列",
        "摘要（最多 3 條）",
    ),
    "terms": (
        "entities",
        "keywords",
        "proper_nouns",
        "people_tools",
        "專有名詞",
        "人物工具",
        "專有名詞 / 人物 / 工具",
    ),
    "content_value": (
        "contentValue",
        "core_value",
        "learning_value",
        "project_value",
        "application_value",
        "value",
        "影片內容核心內容價值提取",
        "核心內容價值",
        "價值內容",
        "專案應用",
    ),
    "source_platform": (
        "sourcePlatform",
        "platform",
        "source",
        "內容來源",
        "內容來源平台",
        "來源平台",
    ),
    "content_category": (
        "contentCategory",
        "category",
        "classification",
        "topic_category",
        "分類",
        "內容分類",
        "主題分類",
    ),
}

SUMMARY_NESTED_KEYS = (
    "summary",
    "ai_summary",
    "learning_summary",
    "AI 提煉摘要",
    "學習摘要",
    "價值內容與分類",
    "value_classification",
    "value_and_classification",
)


def _summary_candidates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [summary]
    for key in SUMMARY_NESTED_KEYS:
        nested = summary.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    return candidates


def _summary_value(summary: dict[str, Any], key: str) -> str:
    for candidate in _summary_candidates(summary):
        for alias in (key, *SUMMARY_ALIASES.get(key, ())):
            value = _to_traditional_text(_format_summary_value(candidate.get(alias, "")).strip())
            if value:
                return value
    return ""


def _limit_key_points(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return "\n".join(lines[:3])


def _compact_topic(value: str) -> str:
    lines = [re.sub(r"^[-*•\d.、\s]+", "", line).strip() for line in value.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    first = lines[0]
    return first[:90] + "..." if len(first) > 90 else first


def _infer_summary_category(summary: dict[str, str]) -> str:
    haystack = " ".join(
        [
            summary.get("explicit_topic", ""),
            summary.get("key_points", ""),
            summary.get("terms", ""),
            summary.get("content_value", ""),
        ]
    ).lower()
    if any(token in haystack for token in ("ai", "llm", "gpt", "model", "prompt", "rag", "agent", "人工智慧")):
        return "AI LLM / 應用"
    if any(token in haystack for token in ("product", "產品", "ux", "app", "使用者", "scale", "database", "資料庫")):
        return "應用 / 學習參考"
    if any(token in haystack for token in ("money", "market", "finance", "stock", "財經", "投資")):
        return "財經"
    if any(token in haystack for token in ("哲學", "思維", "decision", "thinking", "心智")):
        return "哲學思維"
    return "學習參考"


def _infer_source_platform(source_url: str) -> str:
    lowered = source_url.lower()
    if "youtube.com" in lowered or "youtu.be" in lowered:
        return "YT"
    if "instagram.com" in lowered:
        return "IG / Reels"
    if "threads.net" in lowered:
        return "Threads"
    if "twitter.com" in lowered or "x.com" in lowered:
        return "X"
    if "facebook.com" in lowered or "fb.watch" in lowered:
        return "FB"
    return "YT"


def _normalize_summary(summary: dict[str, Any], source_url: str = "") -> dict[str, str]:
    keys = ("explicit_topic", "key_points", "terms", "content_value", "source_platform", "content_category")
    normalized = {key: _summary_value(summary, key) for key in keys}
    if not normalized["explicit_topic"].strip():
        normalized["explicit_topic"] = "\n".join(
            filter(
                None,
                [
                    _format_summary_value(summary.get("chapter_summary", "")).strip(),
                    _format_summary_value(summary.get("quotes", "")).strip(),
                ],
            )
        )
    normalized["explicit_topic"] = _compact_topic(_to_traditional_text(normalized["explicit_topic"]))
    normalized["key_points"] = _limit_key_points(_to_traditional_text(normalized["key_points"]))
    if not normalized["content_value"].strip():
        value_source = normalized["explicit_topic"] or normalized["key_points"] or normalized["terms"]
        if value_source:
            normalized["content_value"] = (
                f"可先對應到本機影片筆記 APP 的內容提煉與專案知識整理流程；"
                f"建議人工確認要連到哪個專案區塊與是否加入雙向連結。參考依據：{value_source[:180]}"
            )
    if not normalized["source_platform"].strip():
        normalized["source_platform"] = _infer_source_platform(source_url)
    if not normalized["content_category"].strip():
        normalized["content_category"] = _infer_summary_category(normalized)
    return normalized
