"""事後補心得：把人工心得追加到筆記的「## 個人心得筆記」段尾（帶日期 callout），
不覆蓋既有人工內容；沒有該段的筆記（如會議筆記）在檔尾補一段。寫入前自動備份。
可選 distill 標記（frontmatter `distill: candidate`）＝這篇含可提取的
prompt/方法/判斷，攢給日後的蒸餾輪用，app 內不做任何自動提取。"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from note_rollback import write_note_with_backup

SECTION = "## 個人心得筆記"


def _upsert_distill(content: str) -> str:
    if content.startswith("---\n"):
        end = content.find("\n---", 4)
        if end != -1:
            head = content[4:end]
            if re.search(r"(?m)^distill:", head):
                head = re.sub(r"(?m)^distill:.*$", "distill: candidate", head, count=1)
            else:
                head = head.rstrip("\n") + "\ndistill: candidate"
            return f"---\n{head}\n{content[end + 1:]}"
    return f"---\ndistill: candidate\n---\n\n{content}"


def _thought_block(text: str, stamp: str) -> str:
    lines = [line.rstrip() for line in text.strip().splitlines() if line.strip()]
    quoted = "\n".join(f"> {line}" for line in lines)
    return f"> [!note] {stamp} 補心得\n{quoted}"


def append_thought(path: str | Path, text: str, distill: bool = False) -> dict[str, Any]:
    target = Path(path)
    content = target.read_text(encoding="utf-8")
    stamp = datetime.now().strftime("%Y-%m-%d")
    block = _thought_block(text, stamp)
    lines = content.splitlines()
    section_at = next((i for i, line in enumerate(lines) if line.strip() == SECTION), None)
    if section_at is None:
        updated = content.rstrip("\n") + f"\n\n{SECTION}\n\n{block}\n"
    else:
        end = next((i for i in range(section_at + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        # trim trailing blanks inside the section so the block sits right after the content
        while end > section_at + 1 and not lines[end - 1].strip():
            end -= 1
        updated = "\n".join(lines[:end] + ["", block, ""] + lines[end:])
        if not updated.endswith("\n"):
            updated += "\n"
    if distill:
        updated = _upsert_distill(updated)
    write = write_note_with_backup(target, updated)
    return {"ok": True, "stamp": stamp, "distill": distill, **write}
