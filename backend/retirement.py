"""退場候選：知識筆記的減法那半（加減並存）。

決定論版（不依賴語意檢索/召回日誌）：候選 = Type1 過時參考 ∧ age>窗 ∧ 未被任何
Type2 引用。Type2（系統自述：架構/原子卡/歷史節點/改版原因）永不入候選。防呆＝被
架構筆記還在引用的舊教學不因「老」就刪——靠「## 相關筆記」的 [[wikilink]] 反向圖。
輸出只是候選清單；實際刪除仍走人工一鍵＋二次確認（觀測餵給人，不自動刪）。
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

DEFAULT_STALE_DAYS = 90
# 資料夾信號（真實 vault 驗出來的）：02_Sources/ 下全是收錄＋時事聚合 = Type1；
# 手寫系統自述（架構/原子卡/歷史，如 root 的 joker_solo）= Type2 永不退場。
_CAPTURE_ROOT = "02_Sources"
_CAPTURE_SOURCE_TYPES = {"article", "video", "short", "pdf"}
# 排除（非知識筆記，不進退場宇宙）：結構檔、垃圾桶、未分流收件匣。
_README_NAMES = {"README.md", "_README.md"}
_TRASH_DIR = "_trash"
_INBOX_ROOT = "01_Inbox"
_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")


def _frontmatter_head(content: str) -> str:
    if not content.startswith("---"):
        return ""
    end = content.find("\n---", 3)
    return content[:end] if end != -1 else ""


def _fm_value(head: str, *keys: str) -> str:
    for key in keys:
        m = re.search(rf"(?m)^{key}:\s*\"?(.+?)\"?\s*$", head)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def _linked_stems(content: str) -> set[str]:
    return {m.group(1).strip() for m in _WIKILINK_RE.finditer(content)}


def _age_days(created: str, today: date) -> Optional[int]:
    m = _DATE_RE.search(created)
    if not m:
        return None
    try:
        return (today - date(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days
    except ValueError:
        return None


def is_excluded(relpath: str) -> bool:
    """結構檔 / 垃圾桶 / 未分流收件匣 → 不算知識筆記，整個排除。"""
    parts = Path(relpath).parts
    if Path(relpath).name in _README_NAMES:
        return True
    if _TRASH_DIR in parts:
        return True
    if parts and parts[0] == _INBOX_ROOT:
        return True
    return False


def classify(relpath: str, head: str) -> str:
    """Type1 = 02_Sources/ 下的收錄＋時事聚合，或有外部來源；否則 Type2 系統自述。"""
    parts = Path(relpath).parts
    if parts and parts[0] == _CAPTURE_ROOT:
        return "type1"
    if _fm_value(head, "source_url", "url", "canonical_url"):
        return "type1"
    if _fm_value(head, "source_type") in _CAPTURE_SOURCE_TYPES:
        return "type1"
    return "type2"


def _iter_notes(root: Path):
    for path in sorted(root.rglob("*.md")):
        relpath = str(path.relative_to(root))
        if is_excluded(relpath):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        yield path, relpath, content


def retirement_candidates(
    vault_root: str,
    stale_days: int = DEFAULT_STALE_DAYS,
    today: Optional[date] = None,
) -> dict[str, Any]:
    root = Path(vault_root)
    today = today or date.today()

    notes: list[dict[str, Any]] = []
    referenced: set[str] = set()  # 被任何 Type2 引用的 stem（防呆豁免集）
    for path, relpath, content in _iter_notes(root):
        head = _frontmatter_head(content)
        kind = classify(relpath, head)
        if kind == "type2":
            referenced |= _linked_stems(content)
        notes.append({
            "path": relpath,
            "stem": path.stem,
            "title": _fm_value(head, "title") or path.stem,
            "kind": kind,
            "created": _fm_value(head, "created", "clipped_at", "date"),
            "age_days": _age_days(_fm_value(head, "created", "clipped_at", "date"), today),
        })

    candidates = [
        n for n in notes
        if n["kind"] == "type1"
        and n["age_days"] is not None
        and n["age_days"] > stale_days
        and n["stem"] not in referenced  # 防呆：被 Type2 引用 → 豁免
    ]
    candidates.sort(key=lambda n: n["age_days"], reverse=True)
    return {
        "schema_id": "yt-retirement-candidates-v1",
        "stale_days": stale_days,
        "candidates": candidates,
        "total": len(candidates),
        "scanned": len(notes),
    }
