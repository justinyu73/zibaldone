"""免費翻譯（雷達判讀用）：Google 翻譯網頁端點（gtx），零成本、無金鑰。

定位：讓使用者快速判斷英文候選「值不值得收」；正式收藏的 AI 摘要本來就輸出
繁中（走付費 LLM）。誠實邊界：gtx 是非官方端點，可能被變更/限流——失敗時回
明確錯誤，UI 提示改讀原文或用 LLM。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Callable

GTX_URL = "https://translate.googleapis.com/translate_a/single"
MAX_CHARS_PER_REQ = 4500
MAX_TOTAL_CHARS = 30000


class FreeTranslateError(RuntimeError):
    pass


def _default_fetch(query: str) -> bytes:
    from radar import _ssl_context  # certifi context（打包版無系統 CA）

    url = f"{GTX_URL}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (yt-note-app)"})
    with urllib.request.urlopen(request, timeout=20, context=_ssl_context()) as response:
        return response.read()


def _chunks(text: str, size: int = MAX_CHARS_PER_REQ) -> list[str]:
    """Split on paragraph boundaries where possible so翻譯不破句."""
    text = text.strip()[:MAX_TOTAL_CHARS]
    if len(text) <= size:
        return [text] if text else []
    parts: list[str] = []
    buffer = ""
    for paragraph in text.split("\n"):
        candidate = f"{buffer}\n{paragraph}" if buffer else paragraph
        if len(candidate) > size and buffer:
            parts.append(buffer)
            buffer = paragraph
        else:
            buffer = candidate
        while len(buffer) > size:  # single huge paragraph → hard split
            parts.append(buffer[:size])
            buffer = buffer[size:]
    if buffer:
        parts.append(buffer)
    return parts


def free_translate_to_zh(text: str, target: str = "zh-TW", fetch_fn: Callable[[str], bytes] | None = None) -> str:
    fetch = fetch_fn or _default_fetch
    pieces: list[str] = []
    for chunk in _chunks(text):
        query = urllib.parse.urlencode({
            "client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": chunk,
        })
        try:
            raw = json.loads(fetch(query))
            segments = raw[0] or []
            pieces.append("".join(str(seg[0]) for seg in segments if seg and seg[0]))
        except Exception as exc:  # noqa: BLE001 - surface a clear, actionable error
            raise FreeTranslateError(f"免費翻譯端點暫時不可用（{exc}）——可先讀原文，或改用 AI 翻譯") from exc
    return "\n".join(pieces).strip()
