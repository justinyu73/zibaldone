"""Shared settings/cost logic: usage cost aggregation, daily cap, and model options."""
from __future__ import annotations

import json
import time
from typing import Any, Dict

from fastapi import HTTPException

import app_config


def _cost_summary() -> Dict[str, Any]:
    from runtime_usage import default_usage_log_path
    path = default_usage_log_path()
    today = time.strftime("%Y-%m-%d")
    today_usd = total_usd = 0.0
    today_calls = total_calls = 0
    by_provider: Dict[str, Dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = ev.get("usage") or {}
            input_price, output_price = app_config.price_for_model(ev.get("model") or "gpt-5-mini")
            calls = int(ev.get("provider_call_count") or 0)
            # estimate-only events (0 provider calls) are previews, not spend
            cost = 0.0 if calls == 0 else (
                ((usage.get("input_tokens") or 0) / 1e6 * input_price)
                + ((usage.get("output_tokens") or 0) / 1e6 * output_price)
            )
            total_usd += cost; total_calls += calls
            prov = ev.get("provider") or "openai"
            bucket = by_provider.setdefault(prov, {"usd": 0.0, "calls": 0})
            bucket["usd"] += cost; bucket["calls"] += calls
            if str(ev.get("observed_at", "")).startswith(today):
                today_usd += cost; today_calls += calls
    daily_cap = float(app_config.get_settings()["daily_cap_usd"])
    return {
        "today_usd": round(today_usd, 4), "today_calls": today_calls,
        "total_usd": round(total_usd, 4), "total_calls": total_calls,
        "daily_cap_usd": daily_cap, "over_daily_cap": today_usd >= daily_cap,
        "by_provider": {p: {"usd": round(v["usd"], 4), "calls": v["calls"]} for p, v in sorted(by_provider.items())},
    }


def _check_daily_cap() -> None:
    summary = _cost_summary()
    if summary["over_daily_cap"]:
        raise HTTPException(429, f"已達每日成本上限 ${summary['daily_cap_usd']}（今日已用 ${summary['today_usd']}）。請在設定調整或明日再試。")


def _range_start_label(range_key: str) -> tuple[str, str]:
    """ISO start date (inclusive) + zh label for today/week/month."""
    import datetime
    now = datetime.date.today()
    if range_key == "today":
        return now.isoformat(), f"本日 {now.isoformat()}"
    if range_key == "week":
        start = now - datetime.timedelta(days=now.weekday())  # 週一
        return start.isoformat(), f"本週 {start.isoformat()} 至 {now.isoformat()}"
    start = now.replace(day=1)
    return start.isoformat(), f"本月 {start.isoformat()} 至 {now.isoformat()}"


_BRAND_BY_PROVIDER = {"openai": "OpenAI", "anthropic": "Anthropic", "google": "Google",
                      "llamacpp": "本機", "cli": "訂閱"}


def _cost_breakdown(range_key: str = "month", start_date: str | None = None, end_date: str | None = None) -> Dict[str, Any]:
    """火力與花費監控表單：階層 大分類(品牌/公司)→小模型，型態(本地/雲)+回合+輸入/輸出/總 token+花費。
    range=today/week/month 按 observed_at 過濾；給 start_date/end_date 則走自訂區間（含上界）。
    estimate-only(0 calls) 不計 spend。動態：前端可依 brand/model 收合與選取。"""
    from runtime_usage import default_usage_log_path
    path = default_usage_log_path()
    if start_date or end_date:
        import datetime
        start = start_date or "0000-01-01"
        end = end_date or datetime.date.today().isoformat()
        label = f"自訂 {start} 至 {end}"
        range_id = "custom"
    else:
        start, label = _range_start_label(range_key)
        end = None
        range_id = range_key
    by_model: Dict[str, Dict[str, Any]] = {}
    total_usd = 0.0
    total_tokens = 0
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            observed = str(ev.get("observed_at", ""))[:10]
            if not observed or observed < start:
                continue
            if end and observed > end:
                continue
            calls = int(ev.get("provider_call_count") or 0)
            if calls == 0:
                continue
            usage = ev.get("usage") or {}
            model = ev.get("model") or "unknown"
            provider = ev.get("provider") or "openai"
            in_tok = int(usage.get("input_tokens") or 0)
            out_tok = int(usage.get("output_tokens") or 0)
            in_price, out_price = app_config.price_for_model(model)
            cost = in_tok / 1e6 * in_price + out_tok / 1e6 * out_price
            b = by_model.setdefault(model, {
                "model": model, "brand": _BRAND_BY_PROVIDER.get(provider, provider.title()),
                "kind": "local" if provider == "llamacpp" else "cloud",
                "provider": provider, "calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0,
            })
            b["calls"] += calls
            b["input_tokens"] += in_tok
            b["output_tokens"] += out_tok
            b["usd"] += cost
            total_usd += cost
            total_tokens += in_tok + out_tok

    # 大分類(品牌)→小模型 階層聚合
    brands: Dict[str, Dict[str, Any]] = {}
    for m in by_model.values():
        m["total_tokens"] = m["input_tokens"] + m["output_tokens"]
        m["usd"] = round(m["usd"], 4)
        g = brands.setdefault(m["brand"], {
            "brand": m["brand"], "kind": m["kind"],
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "usd": 0.0, "models": [],
        })
        for k in ("calls", "input_tokens", "output_tokens", "total_tokens"):
            g[k] += m[k]
        g["usd"] += m["usd"]
        g["models"].append(m)
    for g in brands.values():
        g["usd"] = round(g["usd"], 4)
        g["models"].sort(key=lambda m: (-m["usd"], -m["total_tokens"]))
    brand_rows = sorted(brands.values(), key=lambda g: (-g["usd"], -g["total_tokens"]))
    return {"range": range_id, "range_label": label,
            "total_usd": round(total_usd, 4), "total_tokens": total_tokens, "brands": brand_rows}


# Provider-aware model registry. Adding Claude/Gemini later = add entries here
# (+ wire that provider's client/key); the settings dropdown needs no change.
MODEL_OPTIONS: Dict[str, Any] = {
    "translate": [
        {"id": "gpt-5-mini", "label": "gpt-5-mini", "provider": "openai", "recommended": True},
        {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash（翻譯快速）", "provider": "google", "recommended": True},
        {"id": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash-Lite（極速省）", "provider": "google"},
        {"id": "gpt-5.2", "label": "gpt-5.2（更高品質）", "provider": "openai"},
        {"id": "gpt-4o-mini", "label": "gpt-4o-mini", "provider": "openai"},
        {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5（快速省）", "provider": "anthropic"},
        {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "provider": "anthropic"},
    ],
    "summary": [
        {"id": "gpt-5.2", "label": "gpt-5.2", "provider": "openai", "recommended": True},
        {"id": "gemini-3.1-pro", "label": "Gemini 3.1 Pro（生成高品質）", "provider": "google", "recommended": True},
        {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash（快速）", "provider": "google"},
        {"id": "gpt-5-mini", "label": "gpt-5-mini（快速省）", "provider": "openai"},
        {"id": "gpt-4o", "label": "gpt-4o", "provider": "openai"},
        {"id": "claude-opus-4-8", "label": "Claude Opus 4.8（高品質）", "provider": "anthropic"},
        {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "provider": "anthropic"},
    ],
    "providers": ["openai", "anthropic", "google"],
}


def model_options() -> Dict[str, Any]:
    # 內建本機 runtime（spec C）：裝好就把本機 llama.cpp 模型併進 translate/summary 下拉；
    # 沒裝 → 原樣降級（不報錯、不出現）。下載走 first-run wizard 的內建安裝流程。
    import providers

    import local_llm_builtin
    local = ([{"id": local_llm_builtin.MODEL_ID,
               "label": local_llm_builtin.MODEL_LABEL, "provider": "llamacpp"}]
             if local_llm_builtin.status()["ready"] else [])
    # 訂閱 CLI（spec B）：同範式——偵測到才出現，零設定、app 端零成本。
    subscription = providers.cli_options()
    extra = local + subscription
    if not extra:
        return MODEL_OPTIONS
    local_providers = list({o["provider"] for o in local})
    extra_providers = local_providers + (["cli"] if subscription else [])
    return {
        "translate": MODEL_OPTIONS["translate"] + extra,
        "summary": MODEL_OPTIONS["summary"] + extra,
        "providers": MODEL_OPTIONS["providers"] + extra_providers,
    }
