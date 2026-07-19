"""Multi-provider LLM routing (OpenAI / Anthropic Claude / Google Gemini /
built-in llama.cpp / 訂閱 CLI).

A single `chat_complete` picks the provider from the model id, calls that SDK
with its own key (from app_config), and returns a normalized {text, usage}.
Adding a provider = one branch here + its key in app_config + models in the
registry; callers (translate / summarize) stay provider-agnostic.
Keyless local routes = built-in llama.cpp（本地 gguf）與訂閱 CLI，皆零雲端成本。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any

import app_config


# 訂閱 CLI provider（spec B, docs/design/no_api_model_routes_spec.md）：借用使用者已
# 登入的訂閱 CLI 做翻譯/摘要，app 端零 API 成本。每家 hardcode 一組非互動呼叫參數
# （固定模式、不暴露飄移選項）；呼叫格式 2026-07-05 實測：stdout 只含答案、雜訊在 stderr。
_CLI_TOOLS: dict[str, dict[str, Any]] = {
    "claude": {"label": "Claude（訂閱）", "argv": lambda p: ["claude", "-p", p, "--output-format", "text"]},
    "codex": {"label": "Codex（訂閱）", "argv": lambda p: ["codex", "exec", "--skip-git-repo-check", p]},
    "gemini": {"label": "Gemini（訂閱）", "argv": lambda p: ["gemini", "-p", p]},
}
_CLI_TIMEOUT_SECONDS = 300

# GUI app（Tauri→sidecar）的 PATH 極簡（macOS LaunchServices 不帶 shell PATH），
# which 找不到 nvm/npm/homebrew 裝的 CLI → 追掃常見安裝位置，回絕對路徑。
_CLI_EXTRA_DIRS = (
    "~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "~/.npm-global/bin",
    # pnpm 的 macOS 預設全域 bin。Gemini CLI 常由 pnpm 安裝；Tauri 從
    # LaunchServices 啟動時沒有 shell PATH，需和 nvm/npm fallback 一樣主動掃描。
    "~/Library/pnpm",
)


def _cli_path(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    import glob
    candidates = [os.path.expanduser(f"{d}/{name}") for d in _CLI_EXTRA_DIRS]
    candidates += sorted(glob.glob(os.path.expanduser(f"~/.nvm/versions/node/*/bin/{name}")), reverse=True)
    if os.name == "nt" and os.environ.get("APPDATA"):
        candidates.append(os.path.join(os.environ["APPDATA"], "npm", f"{name}.cmd"))
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def cli_options() -> list[dict[str, Any]]:
    """裝了哪些訂閱 CLI → 下拉選項；只驗存在（登入狀態呼叫時才會知道）。沒裝＝不出現。
    設定 cli_providers_enabled 預設關（TOS 灰色帶，須知情開啟）＝關著一律空。"""
    if not app_config.get_settings().get("cli_providers_enabled"):
        return []
    return [
        {"id": f"cli:{name}", "label": spec["label"], "provider": "cli"}
        for name, spec in _CLI_TOOLS.items()
        if _cli_path(name)
    ]


class ProviderError(RuntimeError):
    pass


def detect_provider(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("cli:"):
        return "cli"
    if m.startswith("llamacpp:"):
        return "llamacpp"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("gemini"):
        return "google"
    return "openai"


def extract_json(text: str) -> dict[str, Any]:
    """Parse JSON, tolerating ```json fences / prose around it (Claude/Gemini)."""
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    elif not raw.startswith("{"):
        brace = re.search(r"\{.*\}", raw, re.DOTALL)
        if brace:
            raw = brace.group(0)
    return json.loads(raw)


def _norm_usage(input_tokens: Any, output_tokens: Any) -> dict[str, Any]:
    it = int(input_tokens or 0)
    ot = int(output_tokens or 0)
    return {"confidence": "exact", "input_tokens": it, "output_tokens": ot, "total_tokens": it + ot}


def chat_complete(*, model: str, prompt: str, system: str | None = None, json_mode: bool = False, json_schema: dict[str, Any] | None = None, max_tokens: int = 4096) -> dict[str, Any]:
    provider = detect_provider(model)
    keyless = provider in ("cli", "llamacpp")
    key = "" if keyless else app_config.get_provider_key(provider)
    if not keyless and not key:
        raise ProviderError(f"{provider} API 金鑰未設定（請到設定填入）")

    if provider == "cli":
        text, usage = _cli_chat(model, prompt, system, json_mode, json_schema)

    elif provider == "llamacpp":
        import local_llm_builtin
        try:
            raw, tokens = local_llm_builtin.chat(prompt, system, json_mode, json_schema, max_tokens)
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc
        text, usage = raw, _norm_usage(tokens.get("input"), tokens.get("output"))

    elif provider == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=key, timeout=120.0)
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        usage = _norm_usage(getattr(resp.usage, "prompt_tokens", 0), getattr(resp.usage, "completion_tokens", 0))

    elif provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=key, timeout=120.0)
        kwargs = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        usage = _norm_usage(resp.usage.input_tokens, resp.usage.output_tokens)

    elif provider == "google":
        from google import genai

        client = genai.Client(api_key=key)
        config: dict[str, Any] = {}
        if system:
            config["system_instruction"] = system
        if json_mode:
            config["response_mime_type"] = "application/json"
        resp = client.models.generate_content(model=model, contents=prompt, config=config or None)
        text = resp.text or ""
        meta = getattr(resp, "usage_metadata", None)
        usage = _norm_usage(getattr(meta, "prompt_token_count", 0), getattr(meta, "candidates_token_count", 0))

    else:
        raise ProviderError(f"unknown provider: {provider}")

    return {"text": text, "usage": usage, "provider": provider, "model": model}


def _cli_chat(model: str, prompt: str, system: str | None, json_mode: bool, json_schema: dict[str, Any] | None):
    tool = model.split(":", 1)[1] if model.lower().startswith("cli:") else model
    spec = _CLI_TOOLS.get(tool)
    if not spec:
        raise ProviderError(f"未知的訂閱 CLI：{tool}")
    path = _cli_path(tool)
    if not path:
        raise ProviderError(f"訂閱 CLI（{tool}）未安裝或不在 PATH——請先安裝並登入，或改選其他模型")
    # CLI 無 system/json 參數（各家旗標不一）→ 統一收進 prompt；JSON 由 extract_json 硬收口。
    full = f"{system}\n\n{prompt}" if system else prompt
    if json_schema:
        full += ("\n\n你必須只輸出一個 JSON 物件（不要 markdown 圍欄、不要任何其他文字），"
                 f"符合此 JSON Schema：\n{json.dumps(json_schema, ensure_ascii=False)}")
    elif json_mode:
        full += "\n\n你必須只輸出一個 JSON 物件，不要 markdown 圍欄、不要任何其他文字。"
    argv = spec["argv"](full)
    argv[0] = path  # 絕對路徑：sidecar 的極簡 PATH 下 subprocess 也找得到
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=_CLI_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(f"訂閱 CLI（{tool}）逾時（{_CLI_TIMEOUT_SECONDS}s）") from exc
    except OSError as exc:
        raise ProviderError(f"訂閱 CLI（{tool}）啟動失敗：{exc}") from exc
    text = (proc.stdout or "").strip()
    if proc.returncode != 0 or not text:
        detail_lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = detail_lines[-1] if detail_lines else f"exit {proc.returncode}"
        raise ProviderError(f"訂閱 CLI（{tool}）呼叫失敗：{detail}——確認已登入（終端機跑一次 {tool}）")
    # 訂閱吃使用者自己的方案額度，app 端記 0 成本、0 token（無可靠 usage 來源，不杜撰）。
    return text, _norm_usage(0, 0)
