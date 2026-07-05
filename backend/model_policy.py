"""Enabled OpenAI model policy for the YT transcript API."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


POLICY_PATH = Path(__file__).with_name("enabled_models.json")
LEGACY_MODEL_ENV = "OPENAI_MODEL"


def load_model_policy() -> Dict[str, Any]:
    data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    tasks = data.get("tasks") if isinstance(data.get("tasks"), dict) else {}
    resolved: Dict[str, Any] = {**data, "tasks": {}}
    for task, config in tasks.items():
        if not isinstance(config, dict):
            continue
        env_name = str(config.get("env") or "").strip()
        fallback = str(config.get("model") or "").strip()
        legacy_fallback = os.getenv(LEGACY_MODEL_ENV, "").strip()
        env_model = os.getenv(env_name, "").strip() if env_name else ""
        model = env_model or fallback or legacy_fallback
        resolved["tasks"][task] = {
            **config,
            "model": model,
            "configured_by": env_name if env_model else "enabled_models.json",
        }
    return resolved


def model_for_task(task: str, fallback: str = "gpt-5-mini") -> str:
    policy = load_model_policy()
    config = policy.get("tasks", {}).get(task, {})
    model = str(config.get("model") or "").strip()
    if model:
        return model
    legacy = os.getenv(LEGACY_MODEL_ENV, "").strip()
    return legacy or fallback


def models_for_task(task: str, fallback: str = "gpt-5-mini") -> list[str]:
    """Resolution chain for a task: [primary, *configured fallbacks]. Local-first —
    fallbacks come ONLY from enabled_models.json tasks.<task>.fallbacks (the operator
    opts in, e.g. a local `ollama:` model as backup); nothing external is auto-added.
    Empty fallbacks = identical to model_for_task (single provider, current behavior)."""
    primary = model_for_task(task, fallback)
    chain = [primary]
    config = load_model_policy().get("tasks", {}).get(task, {})
    for fb in config.get("fallbacks") or []:
        fb = str(fb).strip()
        if fb and fb not in chain:
            chain.append(fb)
    return chain
