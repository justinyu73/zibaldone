"""手機收錄通道：掃描 vault 的 01_Inbox/（手機經 Obsidian / iCloud 丟進來的檔案），
抽出網址當「待收候選」，並把丟進來的 PDF 轉成可閱讀筆記（文字層走 markitdown，
純掃描圖片走本地 OCR）。使用者的檔案本身不動；忽略或帶入後以指紋記在 app
資料區（同雷達慣例），重掃不再出現。"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from news_source_to_note import source_hash

URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
YT_RE = re.compile(r"(youtube\.com/(watch|shorts)|youtu\.be/)", re.I)
SCAN_EXTS = {".md", ".txt"}
MAX_FILE_BYTES = 512 * 1024  # phone captures are small; skip accidental large files


def _state_path() -> Path:
    base = Path(os.getenv("YT_NOTE_APP_CONFIG_DIR", str(Path.home() / ".config" / "yt-note-app")))
    base.mkdir(parents=True, exist_ok=True)
    return base / "capture_inbox.json"


def _load_seen() -> dict[str, str]:
    path = _state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    return data.get("seen", {}) if isinstance(data, dict) else {}


def dismiss(ids: list[str]) -> dict[str, Any]:
    """忽略或帶入後永久記指紋（檔案不動，重掃不再出現）."""
    seen = _load_seen()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for candidate_id in ids:
        seen[str(candidate_id)] = stamp
    path = _state_path()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"seen": seen}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return {"ok": True}


def scan_capture_inbox(vault_root: str) -> dict[str, Any]:
    inbox = Path(vault_root) / "01_Inbox"
    items: list[dict[str, Any]] = []
    if inbox.is_dir():
        seen = _load_seen()
        found: set[str] = set()
        for path in sorted(inbox.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SCAN_EXTS:
                continue
            if "_trash" in path.parts:
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in text.splitlines():
                for url in URL_RE.findall(line):
                    url = url.rstrip(".,;:!?")
                    candidate_id = source_hash(url)
                    if candidate_id in seen or candidate_id in found:
                        continue
                    found.add(candidate_id)
                    items.append({
                        "id": candidate_id,
                        "url": url,
                        "kind": "video" if YT_RE.search(url) else "article",
                        "file": path.relative_to(inbox).as_posix(),
                        "hint": line.strip()[:120],
                    })
    items.extend(scan_capture_pdfs(vault_root))
    return {"items": items, "total": len(items)}


# --- PDF 收錄（markitdown v1，JY 批准 2026-06-12）---
# AC：丟 PDF 進 01_Inbox → 轉出可閱讀 md 筆記（status: inbox）＋原檔移入
# _attachments 並在筆記內連結；轉壞給明確錯誤不靜默。圖片 OCR/Word/PPT 不在 v1。

PDF_MAX_BYTES = 50 * 1024 * 1024


class OcrUnavailable(RuntimeError):
    """本地 OCR 元件（rapidocr-onnxruntime + PyMuPDF）尚未安裝。"""


def _markitdown_text(src: Path) -> str:
    from markitdown import MarkItDown
    result = MarkItDown(enable_plugins=False).convert(str(src))
    return (result.text_content or "").strip()


def _ocr_pdf(src: Path) -> str:
    """掃描型 PDF（無文字層）→ 每頁 render 成圖 → RapidOCR 抽字。本地、零雲端、
    零金鑰。依賴可選：沒裝時拋 OcrUnavailable，呼叫端回明確提示而非靜默。"""
    try:
        import fitz  # PyMuPDF
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise OcrUnavailable(str(exc)) from exc
    engine = RapidOCR()
    pages: list[str] = []
    with fitz.open(str(src)) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=200, alpha=False)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            result, _ = engine(img)
            if result:
                pages.append("\n".join(line[1] for line in result))
    return "\n\n".join(pages).strip()


def _pdf_id(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "pdf-" + h.hexdigest()[:16]


def scan_capture_pdfs(vault_root: str) -> list[dict[str, Any]]:
    """列出 01_Inbox 裡尚未處理的 PDF（指紋同 dismiss 機制，轉換/忽略後不再出現）."""
    inbox = Path(vault_root) / "01_Inbox"
    items: list[dict[str, Any]] = []
    if not inbox.is_dir():
        return items
    seen = _load_seen()
    for path in sorted(inbox.rglob("*.pdf")):
        if not path.is_file() or "_trash" in path.parts:
            continue
        try:
            if path.stat().st_size > PDF_MAX_BYTES:
                continue
            candidate_id = _pdf_id(path)
        except OSError:
            continue
        if candidate_id in seen:
            continue
        items.append({
            "id": candidate_id,
            "url": "",
            "kind": "pdf",
            "file": path.relative_to(inbox).as_posix(),
            "hint": path.name,
        })
    return items


def convert_pdf_capture(vault_root: str, file_relpath: str) -> dict[str, Any]:
    """PDF → md 筆記（markitdown）＋原檔移入 _attachments。回傳 ok/錯誤原因."""
    from obsidian import _dump_frontmatter, now_date, now_stamp
    from news_vault_write import write_news_note

    inbox = (Path(vault_root) / "01_Inbox").resolve()
    src = (inbox / file_relpath).resolve()
    if not str(src).startswith(str(inbox) + os.sep) and src.parent != inbox:
        return {"ok": False, "reason": "bad_path", "message": "檔案必須位於 01_Inbox 內"}
    if not src.is_file() or src.suffix.lower() != ".pdf":
        return {"ok": False, "reason": "not_found", "message": f"找不到 PDF：{file_relpath}"}
    with src.open("rb") as f:
        if f.read(5) != b"%PDF-":
            return {"ok": False, "reason": "invalid_pdf",
                    "message": "這不是有效的 PDF 檔（檔頭不符）——可能是改了副檔名或下載不完整"}

    try:
        text = _markitdown_text(src)
    except Exception as exc:  # markitdown 對壞檔丟多種例外；統一轉明確訊息
        return {"ok": False, "reason": "convert_failed",
                "message": f"PDF 轉換失敗（檔案可能損壞或加密）：{exc}"}
    origin = "PDF 轉換"
    if not text:
        # 無文字層＝純掃描圖片 PDF：本地 OCR 補救（依賴可選，沒裝給明確提示）
        try:
            text = _ocr_pdf(src)
            origin = "PDF OCR"
        except OcrUnavailable:
            return {"ok": False, "reason": "ocr_unavailable",
                    "message": "這是純掃描圖片 PDF，需要 OCR；本機尚未安裝 OCR 元件"
                               "（pip install rapidocr-onnxruntime PyMuPDF）"}
        except Exception as exc:  # noqa: BLE001 - OCR 對壞圖丟多種例外
            return {"ok": False, "reason": "ocr_failed", "message": f"OCR 失敗：{exc}"}
        if not text:
            return {"ok": False, "reason": "empty_text",
                    "message": "OCR 也讀不出文字——可能是空白頁或品質太低的掃描，請改貼文字"}

    candidate_id = _pdf_id(src)
    title = src.stem
    attach_dir = Path(vault_root) / "_attachments"
    attach_dir.mkdir(parents=True, exist_ok=True)
    dest = attach_dir / src.name
    n = 1
    while dest.exists():
        dest = attach_dir / f"{src.stem}-{n}{src.suffix}"
        n += 1

    today = now_date()
    attach_rel = f"_attachments/{dest.name}"
    frontmatter = _dump_frontmatter({
        "type": "source",
        "source": "pdf",
        "source_type": "pdf",
        "url": attach_rel,
        "source_hash": candidate_id,
        "title": title,
        "clipped_at": now_stamp(),
        "status": "inbox",
        "next_action": "review",
        "created": today,
        "updated": today,
        "lifecycle": "active",
        "tags": ["type/source", "source/pdf", "status/inbox"],
    })
    note = "\n".join([
        frontmatter, "",
        f"# {title}", "",
        "> [!info] 來源資訊",
        f"> - 原始檔：[[{attach_rel}|{dest.name}]]",
        f"> - 收錄：{now_stamp()}", "",
        "## 個人心得筆記", "", "- ", "",
        f"## 原文（{origin}）", "",
        text, "",
        "---", f"*saved at {now_stamp()}*",
    ]) + "\n"

    written = write_news_note(
        vault_path=vault_root, subfolder="02_Sources/articles",
        source_hash=candidate_id, url=attach_rel, title=title, note_markdown=note,
    )
    os.replace(src, dest)  # 寫筆記成功後才搬原檔
    dismiss([candidate_id])
    return {"ok": True, "note": written, "attachment": attach_rel, "title": title}
