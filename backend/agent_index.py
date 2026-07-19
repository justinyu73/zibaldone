"""Generate a local, derived Markdown index for coding/research agents.

The vault remains the authority.  This module only projects note metadata and
links into ``_zibaldone/agent-index/`` after an explicit user action; it never
calls a model, network, connector, or scheduler.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


AGENT_INDEX_VERSION = 1
AGENT_INDEX_DIR = "_zibaldone/agent-index"
AGENT_INDEX_PATH = f"{AGENT_INDEX_DIR}/index.md"
AGENT_MANIFEST_PATH = f"{AGENT_INDEX_DIR}/manifest.json"
AGENT_INDEX_START = "<!-- zibaldone:agent-index:start -->"
AGENT_INDEX_END = "<!-- zibaldone:agent-index:end -->"
MAX_NOTES = 5000

_FRONTMATTER_RE = re.compile(r"\A(?:\ufeff)?---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]+)?\]\]")
_MARKDOWN_LINK_RE = re.compile(r"\]\((?!https?://|mailto:|#)([^)]+)\)")
_SKIP_DIRS = {".git", ".obsidian", "_attachments", "_trash", "_zibaldone"}
_METADATA_KEYS = {
    "type",
    "title",
    "description",
    "summary",
    "status",
    "updated",
    "created",
    "updated_at",
    "created_at",
    "clipped_at",
    "status_changed_at",
    "tags",
    "source",
    "source_type",
    "source_url",
    "url",
    "canonical_url",
    "category",
    "content_category",
    "next_action",
}


class AgentIndexError(ValueError):
    """A user-correctable Agent Bridge input or output boundary error."""


def _vault_root(vault_root: str) -> Path:
    root = Path(str(vault_root or "")).expanduser().resolve()
    if not str(vault_root or "").strip():
        raise AgentIndexError("未設定筆記庫根目錄（vault root）")
    if not root.exists():
        raise AgentIndexError(f"筆記庫根目錄不存在：{root}")
    if not root.is_dir():
        raise AgentIndexError(f"筆記庫根目錄不是資料夾：{root}")
    return root


def _parse_scalar(value: str) -> str | list[str]:
    value = value.strip()
    if not value or value in {"~", "null", "Null", "NULL"}:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        if value[0] == '"':
            try:
                return str(json.loads(value))
            except json.JSONDecodeError:
                pass
        return value[1:-1].replace("\\'", "'")
    if value.startswith("[") and value.endswith("]"):
        try:
            return [str(item).strip() for item in next(csv.reader([value[1:-1]], skipinitialspace=True), []) if str(item).strip()]
        except (csv.Error, StopIteration):
            return [item.strip().strip('"\'') for item in value[1:-1].split(",") if item.strip()]
    return value


def _frontmatter(content: str) -> dict[str, str | list[str]]:
    match = _FRONTMATTER_RE.search(content)
    if not match:
        return {}
    fields: dict[str, str | list[str]] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in _METADATA_KEYS:
            fields[key] = _parse_scalar(value)
    return fields


def _text_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return sorted({str(item).strip() for item in value if str(item).strip()})
    return sorted({item.strip() for item in re.split(r"[,\n]", str(value or "")) if item.strip()})


def _heading_title(content: str, fallback: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", content)
    return match.group(1).strip() if match else fallback


def _relative_links(content: str) -> list[str]:
    links: set[str] = set()
    for match in _WIKILINK_RE.finditer(content):
        value = match.group(1).strip()
        if value:
            links.add(f"[[{value}]]")
    for match in _MARKDOWN_LINK_RE.finditer(content):
        value = match.group(1).strip().split(" ", 1)[0]
        if value.endswith(".md") or ".md#" in value:
            links.add(value)
    return sorted(links)[:20]


def _skip_path(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part.startswith(".") or part in _SKIP_DIRS for part in relative.parts[:-1]) or path.name.startswith(".")


def _record(root: Path, path: Path) -> dict[str, Any] | None:
    try:
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            return None
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    rel = path.relative_to(root).as_posix()
    fields = _frontmatter(content)
    title = _text_value(fields.get("title")) or _heading_title(content, path.stem)
    note_type = _text_value(fields.get("type")) or "note"
    description = _text_value(fields.get("description")) or _text_value(fields.get("summary"))
    updated = next(
        (_text_value(fields.get(key)) for key in ("updated", "updated_at", "status_changed_at", "clipped_at", "created", "created_at") if _text_value(fields.get(key))),
        "",
    )
    source_url = next(
        (_text_value(fields.get(key)) for key in ("canonical_url", "source_url", "url") if _text_value(fields.get(key))),
        "",
    )
    return {
        "path": rel,
        "title": title,
        "type": note_type,
        "description": description[:240],
        "status": _text_value(fields.get("status")),
        "updated": updated,
        "created": _text_value(fields.get("created") or fields.get("created_at")),
        "tags": _tags(fields.get("tags")),
        "source": _text_value(fields.get("source")) or _text_value(fields.get("source_type")),
        "source_url": source_url,
        "category": _text_value(fields.get("category")) or _text_value(fields.get("content_category")),
        "next_action": _text_value(fields.get("next_action")),
        "links": _relative_links(content),
    }


def scan_vault(vault_root: str) -> dict[str, Any]:
    """Read visible Markdown metadata only; never mutates the vault."""
    root = _vault_root(vault_root)
    records: list[dict[str, Any]] = []
    skipped = 0
    candidates = sorted(root.rglob("*.md"), key=lambda item: item.relative_to(root).as_posix())
    truncated = False
    for path in candidates:
        if _skip_path(root, path):
            continue
        if len(records) >= MAX_NOTES:
            truncated = True
            break
        record = _record(root, path)
        if record is None:
            skipped += 1
            continue
        records.append(record)
    return {"root": root, "records": records, "skipped_count": skipped, "truncated": truncated}


def _link_target(index_path: str) -> str:
    return quote(f"../../{index_path}", safe="/:@-_.~()")


def render_index(records: list[dict[str, Any]], *, skipped_count: int = 0, truncated: bool = False) -> str:
    lines = [
        "# Zibaldone Agent Index",
        "",
        AGENT_INDEX_START,
        "> This is a generated projection for coding and research agents.",
        "> The vault's Markdown files remain the source of truth; do not edit this index as canonical content.",
        "> Refresh it manually from Zibaldone when the vault changes.",
        AGENT_INDEX_END,
        "",
        "## Scope",
        "",
        f"- Indexed notes: {len(records)}",
        f"- Skipped files: {skipped_count}",
        f"- Scan truncated at {MAX_NOTES}: {'yes' if truncated else 'no'}",
        "- Privacy boundary: metadata and local relative links only; no provider, connector, or network call.",
        "",
    ]
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        group = record["path"].split("/", 1)[0] if "/" in record["path"] else "(root)"
        groups.setdefault(group, []).append(record)
    if not records:
        lines.extend(["## Notes", "", "No visible Markdown notes found.", ""])
        return "\n".join(lines)
    for group in sorted(groups):
        items = groups[group]
        lines.extend([f"## {group} ({len(items)})", ""])
        for record in items:
            metadata = [f"type: {record['type']}"]
            for key in ("status", "updated", "category", "source"):
                if record.get(key):
                    metadata.append(f"{key}: {record[key]}")
            lines.append(f"- [{record['title']}]({_link_target(record['path'])}) — {'; '.join(metadata)}")
            if record.get("description"):
                lines.append(f"  - description: {record['description']}")
            if record.get("tags"):
                lines.append(f"  - tags: {', '.join(record['tags'])}")
            if record.get("source_url"):
                lines.append(f"  - source: {record['source_url']}")
            if record.get("links"):
                lines.append(f"  - relations: {', '.join(record['links'])}")
        lines.append("")
    return "\n".join(lines)


def _managed_index(path: Path) -> bool:
    try:
        return AGENT_INDEX_START in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("generated_by") == "zibaldone" else None


def _atomic_write(path: Path, content: str) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)


def generate_agent_index(vault_root: str, *, write: bool = False, confirm: bool = False) -> dict[str, Any]:
    """Build an index, optionally writing only Zibaldone-owned derived files."""
    if write and not confirm:
        raise AgentIndexError("產生 Agent 索引需要明確確認（confirm=true）")
    scanned = scan_vault(vault_root)
    root: Path = scanned["root"]
    index_text = render_index(
        scanned["records"], skipped_count=scanned["skipped_count"], truncated=scanned["truncated"]
    )
    index_hash = hashlib.sha256(index_text.encode("utf-8")).hexdigest()
    index_path = root / AGENT_INDEX_PATH
    manifest_path = root / AGENT_MANIFEST_PATH
    previous = _read_manifest(manifest_path)
    previous_hash = str(previous.get("index_sha256")) if previous else ""
    changed = previous_hash != index_hash or not index_path.is_file()
    generated = False
    if write and changed:
        if index_path.exists() and not _managed_index(index_path):
            raise AgentIndexError(f"不覆寫非 Zibaldone 產生的索引：{AGENT_INDEX_PATH}")
        if manifest_path.exists() and previous is None:
            raise AgentIndexError(f"不覆寫非 Zibaldone 產生的 manifest：{AGENT_MANIFEST_PATH}")
        output_dir = root / AGENT_INDEX_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(index_path, index_text)
        manifest = {
            "agent_index_version": AGENT_INDEX_VERSION,
            "generated_by": "zibaldone",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source_of_truth": "vault_markdown",
            "scope": "visible_markdown_metadata_and_links",
            "index_path": AGENT_INDEX_PATH,
            "manifest_path": AGENT_MANIFEST_PATH,
            "index_sha256": index_hash,
            "note_count": len(scanned["records"]),
            "skipped_count": scanned["skipped_count"],
            "truncated": scanned["truncated"],
            "records": scanned["records"],
        }
        _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        generated = True
    return {
        "ok": True,
        "dry_run": not write,
        "generated": generated,
        "changed": changed,
        "index_path": AGENT_INDEX_PATH,
        "manifest_path": AGENT_MANIFEST_PATH,
        "note_count": len(scanned["records"]),
        "skipped_count": scanned["skipped_count"],
        "truncated": scanned["truncated"],
        "index_sha256": index_hash,
    }


def agent_index_status(vault_root: str) -> dict[str, Any]:
    root = _vault_root(vault_root)
    index_path = root / AGENT_INDEX_PATH
    manifest_path = root / AGENT_MANIFEST_PATH
    manifest = _read_manifest(manifest_path)
    return {
        "ok": True,
        "index_path": AGENT_INDEX_PATH,
        "manifest_path": AGENT_MANIFEST_PATH,
        "exists": index_path.is_file(),
        "managed": bool(manifest and _managed_index(index_path)),
        "agent_index_version": manifest.get("agent_index_version") if manifest else None,
        "generated_at": manifest.get("generated_at") if manifest else None,
        "note_count": manifest.get("note_count", 0) if manifest else 0,
        "index_sha256": manifest.get("index_sha256", "") if manifest else "",
    }
