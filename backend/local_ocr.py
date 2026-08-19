"""Local, keyless OCR for sampled video frames — client side.

The OCR engine (RapidOCR + OpenCV + onnxruntime, ~150MB zip) no longer ships inside
the main sidecar; it is a downloadable OCR pack built from ocr_pack_main.py and
installed on first use by ocr_runtime.py. This module is a thin stdin/stdout
JSON client of that pack's `serve` mode. The public API (LocalOcrUnavailable,
ensure_ready, extract_text, texts_from_result) is unchanged so callers
(production_extractor, tests) need no changes.
"""
from __future__ import annotations

import base64
import json
import subprocess
import threading
from typing import Any, Iterable


class LocalOcrUnavailable(RuntimeError):
    """Raised when the downloadable OCR pack is not installed or cannot run."""


_LOCK = threading.Lock()
_PROC: subprocess.Popen | None = None


def _pack_exe() -> str:
    from ocr_runtime import pack_executable

    exe = pack_executable()
    if exe is None:
        raise LocalOcrUnavailable(
            "本機 OCR 引擎尚未下載；請在無字幕影片流程點「下載本機 OCR 引擎」（一次性），"
            "或設定 OPENAI_API_KEY 使用雲端 OCR"
        )
    return exe


def _engine() -> subprocess.Popen:
    """Return the running pack process, starting it (and the OCR engine) once."""
    global _PROC
    with _LOCK:
        if _PROC is not None and _PROC.poll() is None:
            return _PROC
        try:
            proc = subprocess.Popen(
                [_pack_exe(), "serve"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            assert proc.stdout is not None
            ready = json.loads(proc.stdout.readline() or "{}")
        except LocalOcrUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — broken pack must surface as guidance, not a 500
            raise LocalOcrUnavailable(f"本機 OCR 引擎啟動失敗（{exc}）；請重新下載本機 OCR 引擎") from exc
        if not ready.get("ok"):
            proc.kill()
            raise LocalOcrUnavailable(
                f"本機 OCR 引擎初始化失敗（{ready.get('error') or 'unknown'}）；請重新下載本機 OCR 引擎"
            )
        _PROC = proc
        return _PROC


def _line_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or "").strip()
    if isinstance(item, (list, tuple)) and len(item) > 1:
        return str(item[1] or "").strip()
    return ""


def texts_from_result(result: Iterable[Any] | None) -> list[str]:
    """Normalize RapidOCR's result rows for deterministic testing and display."""
    return [text for text in (_line_text(item) for item in (result or [])) if text]


def ensure_ready() -> None:
    """Start the pack once so a missing/broken pack fails before any download."""
    _engine()


def extract_text(image_bytes: bytes) -> str:
    """Run the OCR pack on one PNG/JPEG frame and return readable lines."""
    global _PROC
    proc = _engine()
    request = json.dumps({"image_base64": base64.b64encode(image_bytes).decode("ascii")})
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(request + "\n")
        proc.stdin.flush()
        response = json.loads(proc.stdout.readline() or "{}")
    except Exception as exc:  # noqa: BLE001 — dead pack: drop it so the next call restarts
        with _LOCK:
            if _PROC is proc:
                _PROC = None
        raise LocalOcrUnavailable(f"本機 OCR 引擎通訊失敗（{exc}）；請重試或重新下載") from exc
    if not response.get("ok"):
        raise LocalOcrUnavailable(f"本機 OCR 辨識失敗（{response.get('error') or 'unknown'}）")
    return str(response.get("text") or "")
