"""Settings routes: setup readiness, cost, model options, runtime settings, keys, update token."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import app_config
from services.readiness import _local_asr_runtime_readiness
from services.settings import _cost_breakdown, _cost_summary, model_options

router = APIRouter()


@router.get("/api/app/setup-readiness")
def app_setup_readiness(vault_root: str = ""):
    """Read-only first-run checks; never creates a folder or writes a note."""
    normalized = app_config.normalize_host_path(vault_root)
    path = Path(normalized).expanduser() if normalized else None
    exists = bool(path and path.exists())
    is_directory = bool(path and path.is_dir())
    providers = app_config.secrets_status().get("providers", {})
    model_options = app_state_model_options()
    local_models = sorted({
        option["id"] for lane in ("translate", "summary")
        for option in model_options.get(lane, [])
        if option.get("provider") == "ollama"
    })
    return {
        "ok": True,
        "vault": {
            "configured": bool(normalized),
            "exists": exists,
            "is_directory": is_directory,
            "readable": bool(is_directory and os.access(path, os.R_OK)),
            "writable": bool(is_directory and os.access(path, os.W_OK)),
        },
        "providers": {
            provider: {
                "key_set": bool(status.get("key_set")),
                "key_hint": status.get("key_hint") or "",
            }
            for provider, status in providers.items()
        },
        "local_models": local_models,
        "local_asr": _local_asr_runtime_readiness(),
        "checks_are_read_only": True,
    }


class ApiKeyReq(BaseModel):
    api_key: str
    provider: str = "openai"


class ProviderReq(BaseModel):
    provider: str = "openai"


class UpdateTokenReq(BaseModel):
    token: str


@router.get("/api/app/cost-summary")
def app_state_cost_summary():
    return _cost_summary()


@router.get("/api/app/cost-breakdown")
def app_state_cost_breakdown(range: str = "month", start: str = "", end: str = ""):
    if start or end:
        import datetime
        try:
            if start:
                datetime.date.fromisoformat(start)
            if end:
                datetime.date.fromisoformat(end)
        except ValueError:
            raise HTTPException(400, "start/end 需為 YYYY-MM-DD")
        if start and end and start > end:
            raise HTTPException(400, "start 不可晚於 end")
        return _cost_breakdown(start_date=start or None, end_date=end or None)
    return _cost_breakdown(range if range in ("today", "week", "month") else "month")


@router.get("/api/app/model-options")
def app_state_model_options():
    return model_options()


@router.get("/api/app/settings")
def app_state_get_settings():
    return app_config.get_settings()


class RuntimeSettingsReq(BaseModel):
    translate_model: Optional[str] = None
    summary_model: Optional[str] = None
    per_job_cap_usd: Optional[float] = None
    daily_cap_usd: Optional[float] = None
    meeting_template: Optional[str] = None
    meeting_glossary: Optional[List[str]] = None
    cli_providers_enabled: Optional[bool] = None


@router.post("/api/app/settings")
def app_state_set_settings(req: RuntimeSettingsReq):
    return app_config.set_settings({k: v for k, v in req.model_dump().items() if v is not None})


@router.get("/api/app/secrets-status")
def app_state_secrets_status():
    return app_config.secrets_status()


def _require_provider(provider: str) -> str:
    provider = (provider or "openai").strip()
    if provider not in app_config.PROVIDERS:
        raise HTTPException(400, f"未知 provider：{provider}")
    return provider


@router.post("/api/app/api-key")
def app_state_set_api_key(req: ApiKeyReq):
    key = req.api_key.strip()
    if not key:
        raise HTTPException(400, "請輸入金鑰")
    app_config.set_provider_key(_require_provider(req.provider), key)
    return app_config.secrets_status()


@router.post("/api/app/api-key-clear")
def app_state_clear_api_key(req: ProviderReq):
    app_config.clear_provider_key(_require_provider(req.provider))
    return app_config.secrets_status()


@router.get("/api/app/update-token")
def app_state_get_update_token():
    # The updater runs client-side (GitHub fetch + Tauri install), so the raw
    # token is returned to the frontend on load — it lives only in app config.
    token = app_config.get_update_token()
    return {"token": token, "set": bool(token), "hint": app_config.key_hint(token)}


@router.post("/api/app/update-token")
def app_state_set_update_token(req: UpdateTokenReq):
    token = req.token.strip()
    if token:
        app_config.set_update_token(token)
    else:
        app_config.clear_update_token()
    return {"set": bool(token), "hint": app_config.key_hint(token)}


@router.post("/api/app/api-key-test")
def app_state_test_api_key(req: ProviderReq):
    provider = _require_provider(req.provider)
    key = app_config.get_provider_key(provider)
    if not key:
        raise HTTPException(400, "尚未設定 API 金鑰")
    try:
        import providers

        # A tiny, cheap round-trip proves the key authenticates with the provider.
        models = {"openai": "gpt-4o-mini", "anthropic": "claude-haiku-4-5-20251001", "google": "gemini-3.1-flash-lite"}
        providers.chat_complete(model=models[provider], prompt="ping", max_tokens=8)
    except Exception as exc:  # noqa: BLE001 - surface auth/network errors to the user
        return {"ok": False, "message": f"金鑰測試失敗：{exc}"}
    return {"ok": True, "message": "金鑰有效"}
