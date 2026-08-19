"""Standalone OCR pack entry point — the keyless local OCR engine (RapidOCR +
OpenCV + onnxruntime) packaged as its own downloadable PyInstaller onedir, so
the main sidecar and installer stay small.

Protocol: `ocr-pack serve` reads one JSON request per line on stdin and writes
one JSON response per line on stdout. The engine loads once and stays warm for
the whole batch of frames.

Request:  {"image_base64": "..."}          (PNG/JPEG frame bytes)
Response: {"ok": true, "text": "line1\\nline2"}  or  {"ok": false, "error": "..."}

`ocr-pack selftest` runs the engine over a generated blank image and exits 0 —
used by the installer to verify the downloaded pack actually starts.
"""
from __future__ import annotations

import base64
import io
import json
import sys

_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


def _extract_text(image_bytes: bytes) -> str:
    import numpy as np
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    result, _ = _engine()(np.asarray(image))
    lines = []
    for item in result or []:
        if isinstance(item, (list, tuple)) and len(item) > 1:
            text = str(item[1] or "").strip()
            if text:
                lines.append(text)
    return "\n".join(lines)


def _serve() -> int:
    # Signal readiness only after the engine loads, so the caller never sends
    # frames into a half-initialised process.
    try:
        _engine()
    except Exception as exc:  # noqa: BLE001 — surface any init failure in-band
        print(json.dumps({"ok": False, "error": f"engine init failed: {exc}"}), flush=True)
        return 1
    print(json.dumps({"ok": True, "ready": True}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            image_bytes = base64.b64decode(request.get("image_base64") or "")
            print(json.dumps({"ok": True, "text": _extract_text(image_bytes)}), flush=True)
        except Exception as exc:  # noqa: BLE001 — one bad frame must not kill the batch
            print(json.dumps({"ok": False, "error": str(exc)}), flush=True)
    return 0


def _selftest() -> int:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 32), "white").save(buf, format="PNG")
    _extract_text(buf.getvalue())
    print("ocr-pack selftest OK")
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "serve":
        return _serve()
    if command == "selftest":
        return _selftest()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
