"""User-level app config + secrets (B1: decouple the API key from the repo).

The OpenAI key moves OUT of the repo's .env into the user's home config
(~/.config/yt-note-app/config.json, perms 600), so the app is independent of
vaultwiki and the key never sits in the repo or gets scanned. The full key is
never returned to the frontend — only a masked hint. env OPENAI_API_KEY is kept
as a dev fallback.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(os.getenv("YT_NOTE_APP_CONFIG_DIR", str(Path.home() / ".config" / "yt-note-app")))
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_app_config() -> dict[str, Any]:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.is_file() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_app_config(config: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)  # owner-only; keep the secret off other local users
    except OSError:
        pass


PROVIDERS = ["openai", "anthropic", "google"]
ENV_KEY = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "google": "GOOGLE_API_KEY"}


def get_provider_key(provider: str) -> str:
    """Config file first, then env (dev fallback)."""
    cfg = load_app_config()
    return str(cfg.get(f"{provider}_api_key") or os.getenv(ENV_KEY.get(provider, ""), "")).strip()


def set_provider_key(provider: str, api_key: str) -> None:
    config = load_app_config()
    config[f"{provider}_api_key"] = api_key.strip()
    _save_app_config(config)
    if ENV_KEY.get(provider):
        os.environ[ENV_KEY[provider]] = api_key.strip()


def clear_provider_key(provider: str) -> None:
    config = load_app_config()
    config.pop(f"{provider}_api_key", None)
    _save_app_config(config)
    if ENV_KEY.get(provider):
        os.environ.pop(ENV_KEY[provider], None)


# Update token: a fine-grained, repo-Contents-read-only GitHub PAT used by the
# updater. Stored at the same security level as the provider keys (config.json,
# perms 600) so the user pastes it once instead of every launch.
def get_update_token() -> str:
    cfg = load_app_config()
    return str(cfg.get("update_token") or os.getenv("YT_NOTE_UPDATE_TOKEN", "")).strip()


def set_update_token(token: str) -> None:
    config = load_app_config()
    config["update_token"] = token.strip()
    _save_app_config(config)


def clear_update_token() -> None:
    config = load_app_config()
    config.pop("update_token", None)
    _save_app_config(config)


# Back-compat aliases (openai).
def get_api_key() -> str:
    return get_provider_key("openai")


def set_api_key(api_key: str) -> None:
    set_provider_key("openai", api_key)


def clear_api_key() -> None:
    clear_provider_key("openai")


def key_hint(key: str) -> str:
    key = (key or "").strip()
    return f"…{key[-4:]}" if len(key) >= 4 else ""


def _provider_status(provider: str) -> dict[str, Any]:
    cfg_key = str(load_app_config().get(f"{provider}_api_key") or "").strip()
    env_key = os.getenv(ENV_KEY.get(provider, ""), "").strip()
    key = cfg_key or env_key
    return {"key_set": bool(key), "key_hint": key_hint(key), "source": "config" if cfg_key else ("env" if env_key else "none")}


def secrets_status() -> dict[str, Any]:
    providers = {p: _provider_status(p) for p in PROVIDERS}
    # Keep top-level openai fields for back-compat with the original B1 UI shape.
    openai = providers["openai"]
    return {**openai, "config_path": str(CONFIG_FILE), "providers": providers}


def load_key_into_env() -> None:
    """Startup: surface configured keys as env vars so all callers see them."""
    cfg = load_app_config()
    for provider in PROVIDERS:
        key = str(cfg.get(f"{provider}_api_key") or "").strip()
        if key and ENV_KEY.get(provider):
            os.environ[ENV_KEY[provider]] = key


# ---- Runtime settings (non-secret): models + cost caps ----
DEFAULT_SETTINGS: dict[str, Any] = {
    # 內建 llama.cpp 為翻譯預設（本地 gguf、免金鑰、零雲端成本），雲端 gpt-5-mini 退為
    # fallback（enabled_models.json tasks.translate.fallbacks）。內建未安裝→鏈自動退雲端。
    "translate_model": "llamacpp:gemma-3-4b-it",
    "summary_model": "gpt-5.2",
    "per_job_cap_usd": 0.03,
    "daily_cap_usd": 0.50,
    "meeting_template": "general",
    "meeting_glossary": [],
    # 訂閱 CLI provider（claude/codex/gemini）預設關（S2）：呼叫使用者訂閱 CLI 屬各家
    # 服務條款灰色帶，須使用者自行知情開啟；開啟後偵測到的 CLI 才會進模型下拉。
    "cli_providers_enabled": False,
}


# Google 已下架 1.5/2.0 系（呼叫回 404 no longer available）；既存設定遷移到
# 對應現役模型，否則使用者存過的舊選擇會永遠打不通
RETIRED_MODEL_MAP = {
    "gemini-1.5-flash": "gemini-3.1-flash-lite",
    "gemini-2.0-flash": "gemini-3.5-flash",
    "gemini-1.5-pro": "gemini-3.1-pro",
}


def get_settings() -> dict[str, Any]:
    config = load_app_config()
    settings = dict(DEFAULT_SETTINGS)
    for key in DEFAULT_SETTINGS:
        if config.get(key) is not None:
            settings[key] = config[key]
    for key in ("translate_model", "summary_model"):
        settings[key] = RETIRED_MODEL_MAP.get(settings[key], settings[key])
    return settings


def set_settings(updates: dict[str, Any]) -> dict[str, Any]:
    config = load_app_config()
    for key, value in updates.items():
        if key in DEFAULT_SETTINGS and value is not None:
            config[key] = value
    _save_app_config(config)
    apply_settings_to_env()
    return get_settings()


def apply_settings_to_env() -> None:
    """Surface configured models as env vars so model_for_task picks them up."""
    settings = get_settings()
    os.environ["OPENAI_TRANSLATE_MODEL"] = str(settings["translate_model"])
    os.environ["OPENAI_SUMMARY_MODEL"] = str(settings["summary_model"])


# ---- Per-model pricing for the cost guard ----
# Approximate public list prices, USD per 1M tokens (input, output). These are
# ESTIMATES used only to drive the cost display + daily cap; override any of them
# via config["model_prices"][model] = {"input": x, "output": y}. Unknown models
# fall back to a conservative-HIGH default so the cap never silently under-counts
# (better to stop early than blow past the budget on an unpriced model).
DEFAULT_MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-5-mini": (0.15, 0.60),
    "gpt-5.2": (1.25, 10.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-8": (15.00, 75.00),
    # Gemini 3 系（JY 提供之官方價目；3/3.5 Flash 取區間中值）；1.5/2.0 系已被
    # Google 下架（404 no longer available），選單與價目一併移除
    "gemini-3.1-pro": (2.00, 12.00),
    "gemini-3.5-flash": (1.00, 6.00),
    "gemini-3.1-flash-lite": (0.25, 1.50),
}
CONSERVATIVE_DEFAULT_PRICE: tuple[float, float] = (15.0, 75.0)


def price_for_model(model: str) -> tuple[float, float]:
    """(input, output) USD per 1M tokens. Config override > built-in table > conservative default."""
    if str(model or "").lower().startswith(("cli:", "llamacpp:")):
        return (0.0, 0.0)  # 內建 llama.cpp / 訂閱 CLI：app 端零 API 成本
    override = (load_app_config().get("model_prices") or {}).get(model)
    if isinstance(override, dict) and override.get("input") is not None and override.get("output") is not None:
        return float(override["input"]), float(override["output"])
    return DEFAULT_MODEL_PRICES.get(model, CONSERVATIVE_DEFAULT_PRICE)


# --- 主機路徑正規化（Windows 打包版 vs WSL dev 後端，2026-06-12）---
# 前端歷史上把 Windows 路徑轉成 /mnt/<x>/（toWslPath，WSL dev 年代的設計）；
# 打包版後端是各平台原生程式：Windows 收到 /mnt/d/... 要翻回 D:\...，
# posix 收到 D:\... 翻成 /mnt/d/...。已存設定不必遷移。
import re as _re

_WSL_PATH_RE = _re.compile(r"^/mnt/([a-zA-Z])/(.*)$")
_WIN_PATH_RE = _re.compile(r"^([a-zA-Z]):[\\/](.*)$")


def normalize_host_path(p: str) -> str:
    s = (p or "").strip()
    if not s:
        return s
    if os.name == "nt":
        m = _WSL_PATH_RE.match(s.replace("\\", "/"))
        if m:
            return f"{m.group(1).upper()}:/{m.group(2)}"
    else:
        m = _WIN_PATH_RE.match(s)
        if m:
            return f"/mnt/{m.group(1).lower()}/" + m.group(2).replace("\\", "/")
    return s
