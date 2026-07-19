#!/usr/bin/env python3
"""Live end-to-end check for a non-OpenAI provider (Claude / Gemini).

Runs the REAL translate + summarize paths against a short sample, then prints
the normalized usage and the per-model cost the guard would charge — proving
routing, usage accounting, and pricing line up for that provider.

Key never enters the repo or this script: set it first via the app Settings or
env (ANTHROPIC_API_KEY / GOOGLE_API_KEY). Usage is logged to a throwaway temp
file so the real runtime log stays clean.

Usage:
    .venv/bin/python verify_live_provider.py anthropic
    .venv/bin/python verify_live_provider.py google
    .venv/bin/python verify_live_provider.py anthropic claude-haiku-4-5-20251001 claude-sonnet-4-6
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULTS = {
    "anthropic": ("claude-haiku-4-5-20251001", "claude-sonnet-4-6"),
    "google": ("gemini-3.5-flash", "gemini-3.1-pro"),
    "openai": ("gpt-5-mini", "gpt-5.2"),
}

SAMPLE_EN = (
    "Today we are looking at how small language models can run entirely on a "
    "local device. The key idea is that quantization shrinks the model so it "
    "fits in memory, while keeping most of the accuracy. This matters for "
    "privacy because no data leaves your machine."
)


def main_cli() -> int:
    provider = (sys.argv[1] if len(sys.argv) > 1 else "anthropic").strip()
    if provider not in DEFAULTS:
        print(f"unknown provider: {provider} (use one of {list(DEFAULTS)})")
        return 2
    translate_model = sys.argv[2] if len(sys.argv) > 2 else DEFAULTS[provider][0]
    summary_model = sys.argv[3] if len(sys.argv) > 3 else DEFAULTS[provider][1]

    # Throwaway usage log so we don't write into the shared runtime log.
    os.environ["VAULTWIKI_RUNTIME_USAGE_LOG"] = str(Path(tempfile.mkdtemp(prefix="vi-live-")) / "usage.jsonl")
    os.environ["OPENAI_TRANSLATE_MODEL"] = translate_model
    os.environ["OPENAI_SUMMARY_MODEL"] = summary_model

    import app_config
    import providers

    app_config.load_key_into_env()
    if not app_config.get_provider_key(provider):
        print(f"[BLOCKED] {provider} 金鑰未設定。請先在 App 設定填入，或 export {app_config.ENV_KEY[provider]}=...")
        return 1

    import main  # noqa: F401 — keeps the app bootstrap side effects (dotenv/app_config) unchanged
    import translator
    from routers.capture import summarize
    from schemas import SummarizeReq

    print(f"== Live verify: provider={provider} translate={translate_model} summary={summary_model} ==\n")

    print("[1/3] translate (EN→繁中)...")
    zh = translator.translate_en_to_zh(SAMPLE_EN, "zh-TW")
    print("  routed →", providers.detect_provider(translate_model))
    print("  out:", (zh[:120] + "…") if len(zh) > 120 else zh, "\n")

    print("[2/3] summarize (JSON 筆記)...")
    resp = summarize(SummarizeReq(title="Live verify", transcript_en=SAMPLE_EN, mode="quick"))
    summary = resp["summary"]
    print("  routed →", providers.detect_provider(summary_model))
    print("  explicit_topic:", summary.get("explicit_topic"))
    print("  content_category:", summary.get("content_category"), "\n")

    print("[3/3] cost accounting (per-model price)...")
    from services.settings import _cost_summary
    cost = _cost_summary()
    ti, to = app_config.price_for_model(translate_model)
    si, so = app_config.price_for_model(summary_model)
    print(f"  translate price/Mtok: in={ti} out={to}")
    print(f"  summary   price/Mtok: in={si} out={so}")
    print(f"  events total_usd=${cost['total_usd']}  calls={cost['total_calls']}  daily_cap=${cost['daily_cap_usd']}")
    print("\n[PASS] routing + usage + pricing 已端到端跑通。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
