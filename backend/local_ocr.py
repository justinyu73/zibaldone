"""Local, keyless OCR for sampled video frames."""
from __future__ import annotations

from io import BytesIO
from typing import Any, Iterable


class LocalOcrUnavailable(RuntimeError):
    """Raised when the optional local OCR runtime is not installed."""


_ENGINE: Any = None


def _engine() -> Any:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise LocalOcrUnavailable(
            "本機 OCR 尚未安裝；請安裝 rapidocr-onnxruntime，或設定 OPENAI_API_KEY 使用雲端 OCR"
        ) from exc
    _ENGINE = RapidOCR()
    return _ENGINE


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
    """Load the engine once so missing optional dependencies fail before download."""
    _engine()


def extract_text(image_bytes: bytes) -> str:
    """Run RapidOCR on one PNG/JPEG frame and return readable lines."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError as exc:
        raise LocalOcrUnavailable(
            "本機 OCR 需要 Pillow 與 numpy；請重新安裝 backend requirements"
        ) from exc
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    result, _ = _engine()(np.asarray(image))
    return "\n".join(texts_from_result(result))
