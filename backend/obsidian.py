"""Build YouTube learning notes, protect manual edits, and maintain the JSON index."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

INDEX_NAME = "_youtube_index.json"
AI_START = "<!-- vaultwiki:ai:start -->"
AI_END = "<!-- vaultwiki:ai:end -->"


def now_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def slugify(value: str, max_words: int = 8) -> str:
    # Keep CJK: Chinese/Japanese/Korean titles used to collapse to the generic
    # "youtube-video" stem, so every note got a meaningless dated filename.
    value = value.lower()
    value = re.sub(r"[^a-z0-9一-鿿぀-ヿ가-힣\s_-]", "", value)
    words = re.split(r"[\s_-]+", value)
    words = [word for word in words if word]
    return "-".join(words[:max_words])[:64].strip("-") or "youtube-video"


def _dump_frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if value is None:
            continue
        if isinstance(value, list):
            inner = ", ".join(f'"{item}"' if " " in str(item) else str(item) for item in value)
            lines.append(f"{key}: [{inner}]")
        elif isinstance(value, str):
            if any(char in value for char in [":", "#", '"', "'", "\n"]):
                escaped = value.replace('"', '\\"').replace("\n", " ")
                lines.append(f'{key}: "{escaped}"')
            else:
                lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def youtube_root(vault_path: str, subfolder: str) -> Path:
    vault = Path(vault_path).expanduser().resolve()
    if not vault.exists():
        raise FileNotFoundError(f"Vault path does not exist: {vault}")
    if not vault.is_dir():
        raise NotADirectoryError(f"Vault path is not a directory: {vault}")
    root = vault / subfolder if subfolder else vault
    root.mkdir(parents=True, exist_ok=True)
    return root


def index_path(vault_path: str, subfolder: str) -> Path:
    return youtube_root(vault_path, subfolder) / INDEX_NAME


def load_index(vault_path: str, subfolder: str) -> dict[str, Any]:
    path = index_path(vault_path, subfolder)
    if not path.exists():
        return {"version": 1, "updated": now_stamp(), "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "updated": now_stamp(), "items": {}}
    if "items" not in data or not isinstance(data["items"], dict):
        data["items"] = {}
    return data


def write_index(vault_path: str, subfolder: str, data: dict[str, Any]) -> None:
    data["version"] = 1
    data["updated"] = now_stamp()
    path = index_path(vault_path, subfolder)
    # Atomic replace: a crash mid-write must never leave a corrupt index —
    # load_index falls back to empty items, which would blank the library
    # and break dedupe with no rebuild path.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def get_existing(vault_path: str, subfolder: str, video_id: str) -> Optional[dict[str, Any]]:
    return load_index(vault_path, subfolder).get("items", {}).get(video_id)


def _language_summary(transcript_en: str, transcript_zh: str, languages: list[str]) -> str:
    if transcript_en and transcript_zh:
        return "英文與中文"
    if transcript_en:
        return "英文"
    if transcript_zh:
        return "中文"
    if languages:
        return ", ".join(languages)
    return "未知"


_AI_HEADING_FIELD = {
    "影片明確主題": "explicit_topic",
    "重點條列": "key_points",
    "專有名詞 / 人物 / 工具": "terms",
    "影片內容核心內容價值提取": "content_value",
    "內容來源": "source_platform",
    "分類": "content_category",
}


def parse_note_fields(content: str) -> dict[str, str]:
    """Parse an existing note's frontmatter title + AI block back into editable fields."""
    fields = {key: "" for key in (
        "title", "explicit_topic", "key_points", "terms",
        "content_value", "source_platform", "content_category", "video_id",
    )}
    video_id_match = re.search(r"(?m)^video_id:\s*\"?([A-Za-z0-9_-]+)\"?\s*$", content)
    if video_id_match:
        fields["video_id"] = video_id_match.group(1)
    title_match = re.search(r"(?m)^title:\s*(.+)$", content)
    if title_match:
        title = title_match.group(1).strip()
        # Quoted frontmatter (titles containing ":" etc.) must round-trip without
        # the quotes leaking into the edit fields / index.
        if len(title) >= 2 and title[0] == '"' and title[-1] == '"':
            title = title[1:-1].replace('\\"', '"')
        fields["title"] = title
    start = content.find(AI_START)
    end = content.find(AI_END)
    if start != -1 and end != -1:
        block = content[start:end]
        parts = re.split(r"(?m)^###\s+(.+?)\s*$", block)
        for index in range(1, len(parts) - 1, 2):
            heading = parts[index].strip()
            body = parts[index + 1].strip()
            field = _AI_HEADING_FIELD.get(heading)
            if field:
                fields[field] = "" if body == "-" else body
    return fields


def _ai_learning_block(ai_summary: dict[str, str], ai_mode: str) -> str:
    explicit_topic = (ai_summary.get("explicit_topic") or "").strip()
    if not explicit_topic:
        explicit_topic = "\n".join(
            filter(
                None,
                [
                    (ai_summary.get("chapter_summary") or "").strip(),
                    (ai_summary.get("quotes") or "").strip(),
                ],
            )
        )
    key_points = "\n".join(
        line.strip()
        for line in (ai_summary.get("key_points") or "").splitlines()
        if line.strip()
    )
    key_points = "\n".join(key_points.splitlines()[:3])
    fields = [
        ("影片明確主題", "explicit_topic"),
        ("重點條列", "key_points"),
        ("專有名詞 / 人物 / 工具", "terms"),
        ("影片內容核心內容價值提取", "content_value"),
        ("內容來源", "source_platform"),
        ("分類", "content_category"),
    ]
    values = {**ai_summary, "explicit_topic": explicit_topic, "key_points": key_points}
    lines = [
        AI_START,
        "## AI 提煉摘要",
        "",
        f"> 模式：{ai_mode or 'manual'}　|　更新：{now_stamp()}",
        "",
    ]
    for heading, key in fields:
        value = (values.get(key) or "").strip()
        lines.extend([f"### {heading}", ""])
        lines.append(value if value else "- ")
        lines.append("")
    lines.append(AI_END)
    return "\n".join(lines)


def _replace_ai_block(existing: str, ai_block: str) -> str:
    start = existing.find(AI_START)
    end = existing.find(AI_END)
    if start >= 0 and end > start:
        end += len(AI_END)
        return existing[:start].rstrip() + "\n\n" + ai_block + "\n\n" + existing[end:].lstrip()
    return existing.rstrip() + "\n\n" + ai_block + "\n"


def build_note(
    *,
    video_id: str,
    url: str,
    title: str,
    channel: str,
    published: Optional[str],
    duration: Optional[str],
    thumbnail: Optional[str],
    transcript_en: str,
    transcript_zh: str,
    ai_summary: dict[str, str],
    ai_mode: str,
    manual_summary: str = "",
    languages: Optional[list[str]] = None,
    failure_class: str = "",
    extraction_sources: Optional[list[str]] = None,
    coverage_summary: str = "",
    is_short: bool = False,
) -> str:
    today = now_date()
    languages = languages or []
    extraction_sources = extraction_sources or []
    source_type = "short" if is_short else "video"
    frontmatter = {
        "type": "source",
        "source": "youtube",
        "source_type": source_type,
        "url": url,
        "canonical_url": f"https://www.youtube.com/watch?v={video_id}",
        "source_hash": video_id,
        "video_id": video_id,
        "title": title,
        "author": channel,
        "duration": duration,
        "posted_at": published,
        "clipped_at": now_stamp(),
        "status": "inbox",
        "next_action": "review",
        "status_changed_at": today,
        "summary": (ai_summary.get("key_points") or manual_summary or "").replace("\n", " ")[:220],
        "created": today,
        "updated": today,
        "last_reviewed": today,
        "lifecycle": "active",
        "quality_score": 3 if ai_summary else 2,
        "language": _language_summary(transcript_en, transcript_zh, languages),
        "transcript_failure_class": failure_class or None,
        "extraction_sources": extraction_sources or None,
        "coverage_summary": coverage_summary or None,
        "tags": ["type/source", "source/youtube", "status/inbox"],
    }

    body = [
        _dump_frontmatter(frontmatter),
        "",
        f"# {title}",
        "",
        "> [!info] 來源資訊",
        f"> - 連結：[{url}]({url})",
        f"> - Canonical：<https://www.youtube.com/watch?v={video_id}>",
    ]
    if channel:
        body.append(f"> - 頻道：{channel}")
    if duration:
        body.append(f"> - 時長：{duration}")
    if languages:
        body.append(f"> - 字幕語言：{', '.join(languages)}")
    if extraction_sources:
        body.append(f"> - 提取來源：{', '.join(extraction_sources)}")
    if failure_class:
        body.append(f"> - 字幕狀態：{failure_class}")
    if coverage_summary:
        body.append(f"> - 覆蓋摘要：{coverage_summary}")
    if thumbnail:
        body.extend(["", f"![thumbnail]({thumbnail})"])

    body.extend(
        [
            "",
            _ai_learning_block(ai_summary, ai_mode),
            "",
            "## 個人心得筆記",
            "",
            manual_summary.strip() if manual_summary.strip() else "- ",
            "",
            "## 逐字稿",
            "",
            "<details><summary>英文逐字稿</summary>",
            "",
            transcript_en.strip() if transcript_en.strip() else "無英文字幕",
            "",
            "</details>",
            "",
            "<details><summary>中文逐字稿</summary>",
            "",
            transcript_zh.strip() if transcript_zh.strip() else "無中文字幕或翻譯",
            "",
            "</details>",
            "",
            "---",
            f"*VaultWiki generated at {now_stamp()}*",
        ],
    )
    return "\n".join(body) + "\n"


def _target_path(root: Path, title: str, is_short: bool, overwrite: bool = False) -> Path:
    folder = root / ("shorts" if is_short else "videos")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{slugify(title)}_yt_{now_date()}.md"
    if overwrite or not target.exists():
        return target
    stem = target.stem
    index = 2
    while True:
        candidate = folder / f"{stem}-{index}.md"
        if not candidate.exists():
            return candidate
        index += 1


def content_hash(*parts: str) -> str:
    joined = "\n".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def save_learning_note(
    *,
    vault_path: str,
    subfolder: str,
    video_id: str,
    url: str,
    title: str,
    channel: str,
    published: Optional[str],
    duration: Optional[str],
    thumbnail: Optional[str],
    transcript_en: str,
    transcript_zh: str,
    ai_summary: dict[str, str],
    ai_mode: str,
    manual_summary: str,
    languages: list[str],
    save_mode: str,
    is_short: bool,
    failure_class: str = "",
    extraction_sources: Optional[list[str]] = None,
    coverage_summary: str = "",
) -> dict[str, Any]:
    if not vault_path:
        raise ValueError("OBSIDIAN_VAULT_PATH is not configured")

    root = youtube_root(vault_path, subfolder)
    vault = Path(vault_path).expanduser().resolve()
    data = load_index(vault_path, subfolder)
    existing = data["items"].get(video_id)
    extraction_sources = extraction_sources or []

    if existing and save_mode == "create":
        raise FileExistsError("This video already exists in the YouTube index")

    note_content = build_note(
        video_id=video_id,
        url=url,
        title=title,
        channel=channel,
        published=published,
        duration=duration,
        thumbnail=thumbnail,
        transcript_en=transcript_en,
        transcript_zh=transcript_zh,
        ai_summary=ai_summary,
        ai_mode=ai_mode,
        manual_summary=manual_summary,
        languages=languages,
        failure_class=failure_class,
        extraction_sources=extraction_sources,
        coverage_summary=coverage_summary,
        is_short=is_short,
    )

    created_new = True
    if existing and save_mode == "update_ai":
        note_path = vault / existing["note_path"]
        if not note_path.exists():
            note_path = _target_path(root, title, is_short)
        else:
            existing_content = note_path.read_text(encoding="utf-8")
            note_content = _replace_ai_block(existing_content, _ai_learning_block(ai_summary, ai_mode))
            created_new = False
    else:
        note_path = _target_path(root, title, is_short)

    note_path.write_text(note_content, encoding="utf-8")
    relative_path = note_path.relative_to(vault).as_posix()
    entry = {
        "video_id": video_id,
        "canonical_url": f"https://www.youtube.com/watch?v={video_id}",
        "original_url": url,
        "title": title,
        "channel": channel,
        "note_path": relative_path,
        "created": existing.get("created") if existing else now_stamp(),
        "updated": now_stamp(),
        "transcript_languages": languages,
        "transcript_failure_class": failure_class,
        "extraction_sources": extraction_sources,
        "coverage_summary": coverage_summary,
        "last_ai_mode": ai_mode,
        "category": (ai_summary.get("content_category") or (existing or {}).get("category") or "").strip(),
        "content_hash": content_hash(transcript_en, transcript_zh, json.dumps(ai_summary, ensure_ascii=False)),
        "manual_protected": True,
        "source_type": "short" if is_short else "video",
        "status": "inbox",
    }
    data["items"][video_id] = entry
    write_index(vault_path, subfolder, data)
    return {"path": str(note_path), "relative_path": relative_path, "entry": entry, "created_new": created_new}
