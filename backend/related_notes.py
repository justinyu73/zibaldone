"""相關筆記：候選＝用筆記自己的標題＋專有名詞當查詢，跑 FTS5 聚合命中數。
候選只是建議；寫入「## 相關筆記」段（[[wikilink]]）由人勾選確認後落檔——
鏈接存在檔案裡，Obsidian 圖譜與之後讀 vault 的 AI 讀到同一張關聯網。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from note_rollback import write_note_with_backup
from obsidian import parse_note_fields
from search_index import search_notes

SECTION = "## 相關筆記"
MAX_QUERIES = 8
# 太短或太泛的詞當查詢只會撈出整庫
_STOP = {"ai", "llm", "the", "and", "for", "with"}


def _queries_from_note(content: str, fallback_title: str) -> list[str]:
    fields = parse_note_fields(content)
    raw: list[str] = []
    for line in (fields.get("terms") or "").splitlines():
        cleaned = line.strip().lstrip("-•").strip()
        raw.extend(part.strip() for part in re.split(r"[，,、/｜|]", cleaned) if part.strip())
    title = (fields.get("title") or fallback_title).strip()
    if title:
        raw.append(title)
    queries: list[str] = []
    for term in raw:
        if len(term) < 2 or term.lower() in _STOP or term in queries:
            continue
        queries.append(term)
    return queries[:MAX_QUERIES]


def _linked_stems(content: str) -> set[str]:
    return {m.group(1).strip() for m in re.finditer(r"\[\[([^\]|#]+)", content)}


def related_candidates(vault_root: str, note_relpath: str, limit: int = 5) -> dict[str, Any]:
    root = Path(vault_root)
    content = (root / note_relpath).read_text(encoding="utf-8")
    queries = _queries_from_note(content, Path(note_relpath).stem)
    already = _linked_stems(content)
    scores: dict[str, dict[str, Any]] = {}
    for query in queries:
        for rec in search_notes(vault_root, query, 10)["records"]:
            if rec["path"] == note_relpath or Path(rec["path"]).stem in already:
                continue
            entry = scores.setdefault(rec["path"], {
                "path": rec["path"], "title": rec["title"], "source": rec["source"],
                "score": 0, "matched": [],
            })
            entry["score"] += 1
            entry["matched"].append(query)
    ranked = sorted(scores.values(), key=lambda e: e["score"], reverse=True)[:limit]
    return {"candidates": ranked, "queries": queries, "total": len(ranked)}


def write_links(vault_root: str, note_relpath: str, paths: list[str]) -> dict[str, Any]:
    """把勾選的關聯寫進「## 相關筆記」段；wikilink 用檔名 stem（Obsidian 以名解析）。"""
    root = Path(vault_root)
    target = root / note_relpath
    content = target.read_text(encoding="utf-8")
    already = _linked_stems(content)
    new_lines = []
    for rel in paths:
        stem = Path(rel).stem
        if stem and stem not in already:
            already.add(stem)
            new_lines.append(f"- [[{stem}]]")
    if not new_lines:
        return {"ok": True, "added": 0}
    lines = content.splitlines()
    section_at = next((i for i, line in enumerate(lines) if line.strip() == SECTION), None)
    if section_at is not None:
        end = next((i for i in range(section_at + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        while end > section_at + 1 and not lines[end - 1].strip():
            end -= 1
        updated = "\n".join(lines[:end] + new_lines + lines[end:])
    else:
        # 放在大塊原始內容（逐字稿/原文）之前、心得之後；都沒有就接在檔尾
        anchor = next((i for i, line in enumerate(lines) if line.strip() in ("## 逐字稿", "## 原文")), None)
        block = [SECTION, ""] + new_lines + [""]
        if anchor is None:
            updated = content.rstrip("\n") + "\n\n" + "\n".join(block)
        else:
            updated = "\n".join(lines[:anchor] + block + lines[anchor:])
    if not updated.endswith("\n"):
        updated += "\n"
    write = write_note_with_backup(target, updated)
    return {"ok": True, "added": len(new_lines), **write}
