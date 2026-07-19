"""Optional OpenAI translation helper."""
from __future__ import annotations

from typing import Callable, List, Optional

from model_policy import models_for_task
from runtime_usage import append_runtime_usage_event

ProgressCallback = Callable[[int, int], None]

MAX_CHARS_PER_REQ = 6000
DEFAULT_MODEL = "gpt-5-mini"

TARGET_NAMES = {
    "zh-TW": "Traditional Chinese used in Taiwan",
    "zh-Hant": "Traditional Chinese",
    "zh": "Chinese",
    "zh-CN": "Simplified Chinese",
    "zh-Hans": "Simplified Chinese",
}


class TranslateError(RuntimeError):
    pass


def _chunk(text: str, size: int = MAX_CHARS_PER_REQ) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: List[str] = []
    buffer: List[str] = []
    current = 0
    for word in text.split():
        # CJK/Japanese transcripts have no spaces, so a "word" can exceed the
        # whole chunk budget — hard-split it instead of emitting an oversized chunk.
        while len(word) > size:
            if buffer:
                chunks.append(" ".join(buffer))
                buffer = []
                current = 0
            chunks.append(word[:size])
            word = word[size:]
        if not word:
            continue
        word_length = len(word) + 1
        if current + word_length > size and buffer:
            chunks.append(" ".join(buffer))
            buffer = []
            current = 0
        buffer.append(word)
        current += word_length
    if buffer:
        chunks.append(" ".join(buffer))
    return chunks


def _complete_with_chain(models: List[str], start: int, prompt: str, system: str):
    """Try models[start:] in order; return (result, idx_used). Advance-only so a dead
    provider isn't retried for later chunks. Raise TranslateError if the whole chain fails."""
    import providers

    errors: List[str] = []
    for idx in range(start, len(models)):
        try:
            return providers.chat_complete(model=models[idx], prompt=prompt, system=system), idx
        except Exception as exc:  # ProviderError or any provider-side failure → try next
            errors.append(f"{models[idx]}: {exc}")
    raise TranslateError("翻譯失敗（fallback chain 全失敗）：" + " | ".join(errors))


def translate_to_zh(
    text: str,
    target: str = "zh-TW",
    progress_callback: Optional[ProgressCallback] = None,
) -> str:
    if not text or not text.strip():
        return ""

    import providers

    models = models_for_task("translate", DEFAULT_MODEL)
    target_name = TARGET_NAMES.get(target, "Traditional Chinese")
    system_prompt = (
        f"Translate the user's transcript (any source language) into {target_name}. "
        "Keep technical terms accurate, preserve paragraph breaks where useful, "
        "and do not add commentary that is not present in the source."
    )

    chunks = _chunk(text)
    total = len(chunks)
    parts: List[str] = []
    agg = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    have_usage = False
    active = 0  # advance-only index into the fallback chain
    for index, chunk in enumerate(chunks, start=1):
        result, active = _complete_with_chain(models, active, chunk, system_prompt)
        parts.append((result["text"] or "").strip())

        usage = result["usage"]
        if usage.get("confidence") == "exact":
            have_usage = True
            for key in agg:
                agg[key] += usage.get(key) or 0
        if progress_callback is not None:
            progress_callback(index, total)

    used_model = models[active]
    if total:
        append_runtime_usage_event(
            task="translate",
            provider=providers.detect_provider(used_model),
            model=used_model,
            mode="chunked",
            endpoint="/api/translate",
            usage={**agg, "confidence": "exact"} if have_usage else {"confidence": "not_available"},
            provider_call_count=total,
            raw_evidence_ref="runtime:translate:chunked_response_usage",
            decision_scope="translate provider usage accounting only; no transcript text stored",
        )

    return "\n".join(part for part in parts if part)
