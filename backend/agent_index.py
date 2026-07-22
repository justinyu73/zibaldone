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


AGENT_INDEX_VERSION = 2
OKF_VERSION = "0.1"
AGENT_INDEX_DIR = "_zibaldone/agent-index"
AGENT_INDEX_PATH = f"{AGENT_INDEX_DIR}/index.md"
AGENT_MANIFEST_PATH = f"{AGENT_INDEX_DIR}/manifest.json"
AGENT_CONCEPT_DIR = f"{AGENT_INDEX_DIR}/concepts"
AGENT_INDEX_START = "<!-- zibaldone:agent-index:start -->"
AGENT_INDEX_END = "<!-- zibaldone:agent-index:end -->"
AGENT_CONCEPT_MARKER = "<!-- zibaldone:okf-concept -->"
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


def _frontmatter_all(content: str) -> dict[str, str | list[str]]:
    match = _FRONTMATTER_RE.search(content)
    if not match:
        return {}
    fields: dict[str, str | list[str]] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        fields[key] = _parse_scalar(value)
    return fields


def _frontmatter(content: str) -> dict[str, str | list[str]]:
    return {key: value for key, value in _frontmatter_all(content).items() if key in _METADATA_KEYS}


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


def _bundle_link_target(bundle_path: str) -> str:
    return quote(bundle_path, safe="/:@-_.~()")


def _concept_path(source_path: str) -> str:
    parts = source_path.split("/")
    if parts[-1] in {"index.md", "log.md"}:
        parts[-1] = f"{Path(parts[-1]).stem}.note.md"
    return "/".join(("concepts", *parts))


def _yaml_string(value: Any) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def _yaml_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _safe_heading(value: str) -> str:
    return " ".join(str(value or "Note").splitlines()).strip() or "Note"


def _source_link(root: Path, concept_path: str, source_path: str) -> str:
    concept_file = root / AGENT_INDEX_DIR / concept_path
    source_file = root / source_path
    relative = os.path.relpath(source_file, start=concept_file.parent).replace(os.sep, "/")
    return quote(relative, safe="/:@-_.~()")


def _render_concept(root: Path, record: dict[str, Any]) -> str:
    source_path = str(record["path"])
    concept_path = _concept_path(source_path)
    lines = ["---", f"type: {_yaml_string(record.get('type') or 'note')}"]
    for key in ("title", "description", "status", "category", "source", "next_action"):
        if record.get(key):
            lines.append(f"{key}: {_yaml_string(record[key])}")
    if record.get("updated") or record.get("created"):
        lines.append(f"timestamp: {_yaml_string(record.get('updated') or record.get('created'))}")
    if record.get("source_url"):
        lines.append(f"resource: {_yaml_string(record['source_url'])}")
    if record.get("tags"):
        lines.append(f"tags: {_yaml_list(record['tags'])}")
    lines.extend(
        [
            f"zibaldone_source_path: {_yaml_string(source_path)}",
            "zibaldone_projection: \"metadata-only\"",
            "---",
            "",
            AGENT_CONCEPT_MARKER,
            f"# {_safe_heading(record['title'])}",
            "",
            "This is a metadata-only OKF projection. The vault note remains the source of truth.",
            "",
            f"Original note: [{source_path}]({_source_link(root, concept_path, source_path)})",
        ]
    )
    if record.get("links"):
        lines.extend(["", "## Relations", ""])
        for link in record["links"]:
            target = str(link)
            if target.startswith("[[") and target.endswith("]]"):
                target = target[2:-2]
            target_path = target.split("#", 1)[0]
            if target_path.endswith(".md"):
                lines.append(f"- [{target}]({_bundle_link_target(_concept_path(target_path))})")
            else:
                lines.append(f"- {link}")
    return "\n".join(lines) + "\n"


def _render_index(
    records: list[dict[str, Any]], *, skipped_count: int = 0, truncated: bool = False
) -> str:
    lines = [
        "---",
        f"okf_version: {_yaml_string(OKF_VERSION)}",
        f"zibaldone_agent_bridge_version: {AGENT_INDEX_VERSION}",
        'zibaldone_generated_by: "zibaldone"',
        f"zibaldone_note_count: {len(records)}",
        f"zibaldone_skipped_count: {skipped_count}",
        f"zibaldone_truncated: {str(truncated).lower()}",
        "---",
        "",
        "# Zibaldone Agent Bundle",
        "",
        AGENT_INDEX_START,
        "> This is a generated OKF v0.1 projection for coding and research agents.",
        "> The vault's Markdown files remain the source of truth; do not edit this bundle as canonical content.",
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
    if not records:
        lines.extend(["## Concepts", "", "No visible Markdown notes found.", ""])
        return "\n".join(lines)
    lines.extend(["## Concepts", ""])
    for record in records:
        concept_path = _concept_path(str(record["path"]))
        metadata = [f"type: {record['type']}"]
        for key in ("status", "updated", "category", "source"):
            if record.get(key):
                metadata.append(f"{key}: {record[key]}")
        lines.append(f"- [{_safe_heading(record['title'])}]({_bundle_link_target(concept_path)}) — {'; '.join(metadata)}")
    lines.append("")
    return "\n".join(lines)


def _render_bundle(root: Path, records: list[dict[str, Any]], *, skipped_count: int, truncated: bool) -> dict[str, str]:
    bundle = {"index.md": _render_index(records, skipped_count=skipped_count, truncated=truncated)}
    for record in records:
        concept_path = _concept_path(str(record["path"]))
        bundle[concept_path] = _render_concept(root, record)
    return bundle


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


def _generated_concepts(root: Path) -> list[Path]:
    concept_root = root / AGENT_CONCEPT_DIR
    if not concept_root.is_dir():
        return []
    generated: list[Path] = []
    for path in sorted(concept_root.rglob("*.md")):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if AGENT_CONCEPT_MARKER in content:
            generated.append(path)
    return generated


def _bundle_changed(root: Path, bundle: dict[str, str]) -> bool:
    for relative, expected in bundle.items():
        path = root / AGENT_INDEX_DIR / relative
        try:
            if path.read_text(encoding="utf-8") != expected:
                return True
        except OSError:
            return True
    expected_paths = {root / AGENT_INDEX_DIR / relative for relative in bundle if relative != "index.md"}
    return any(path not in expected_paths for path in _generated_concepts(root))


def _protect_bundle_outputs(root: Path, bundle: dict[str, str]) -> None:
    index_path = root / AGENT_INDEX_PATH
    if index_path.exists() and not _managed_index(index_path):
        raise AgentIndexError(f"不覆寫非 Zibaldone 產生的索引：{AGENT_INDEX_PATH}")
    manifest_path = root / AGENT_MANIFEST_PATH
    if manifest_path.exists() and _read_manifest(manifest_path) is None:
        raise AgentIndexError(f"不覆寫非 Zibaldone 產生的 manifest：{AGENT_MANIFEST_PATH}")
    concept_root = root / AGENT_CONCEPT_DIR
    expected_paths = {root / AGENT_INDEX_DIR / relative for relative in bundle if relative != "index.md"}
    if concept_root.is_dir():
        for path in concept_root.rglob("*.md"):
            if path not in expected_paths and AGENT_CONCEPT_MARKER not in path.read_text(encoding="utf-8", errors="replace"):
                raise AgentIndexError(f"不覆寫 Agent Bridge concepts 下的使用者檔案：{path.relative_to(root).as_posix()}")
            if path in expected_paths and AGENT_CONCEPT_MARKER not in path.read_text(encoding="utf-8", errors="replace"):
                raise AgentIndexError(f"不覆寫非 Zibaldone 產生的 concept：{path.relative_to(root).as_posix()}")


def _remove_stale_generated_concepts(root: Path, bundle: dict[str, str]) -> None:
    expected_paths = {root / AGENT_INDEX_DIR / relative for relative in bundle if relative != "index.md"}
    for path in _generated_concepts(root):
        if path in expected_paths:
            continue
        path.unlink()
        parent = path.parent
        concept_root = root / AGENT_CONCEPT_DIR
        while parent != concept_root and parent != root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def _atomic_write(path: Path, content: str) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)


def generate_agent_index(vault_root: str, *, write: bool = False, confirm: bool = False) -> dict[str, Any]:
    """Build an OKF bundle, optionally writing only Zibaldone-owned files."""
    if write and not confirm:
        raise AgentIndexError("產生 Agent 索引需要明確確認（confirm=true）")
    scanned = scan_vault(vault_root)
    root: Path = scanned["root"]
    bundle = _render_bundle(
        root,
        scanned["records"],
        skipped_count=scanned["skipped_count"],
        truncated=scanned["truncated"],
    )
    index_text = bundle["index.md"]
    index_hash = hashlib.sha256(index_text.encode("utf-8")).hexdigest()
    index_path = root / AGENT_INDEX_PATH
    manifest_path = root / AGENT_MANIFEST_PATH
    previous = _read_manifest(manifest_path)
    changed = _bundle_changed(root, bundle) or previous is not None
    generated = False
    if write and changed:
        _protect_bundle_outputs(root, bundle)
        output_dir = root / AGENT_INDEX_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        _remove_stale_generated_concepts(root, bundle)
        _atomic_write(index_path, index_text)
        for relative, content in bundle.items():
            if relative == "index.md":
                continue
            destination = root / AGENT_INDEX_DIR / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(destination, content)
        if previous is not None and manifest_path.exists():
            manifest_path.unlink()
        generated = True
    return {
        "ok": True,
        "dry_run": not write,
        "generated": generated,
        "changed": changed,
        "bundle_path": AGENT_INDEX_DIR,
        "index_path": AGENT_INDEX_PATH,
        "manifest_path": None,
        "okf_version": OKF_VERSION,
        "agent_index_version": AGENT_INDEX_VERSION,
        "concept_count": len(scanned["records"]),
        "note_count": len(scanned["records"]),
        "skipped_count": scanned["skipped_count"],
        "truncated": scanned["truncated"],
        "index_sha256": index_hash,
    }


def agent_index_status(vault_root: str) -> dict[str, Any]:
    root = _vault_root(vault_root)
    index_path = root / AGENT_INDEX_PATH
    metadata: dict[str, Any] = {}
    index_hash = ""
    generated_at = None
    if index_path.is_file():
        try:
            index_content = index_path.read_text(encoding="utf-8")
            metadata = _frontmatter_all(index_content)
            index_hash = hashlib.sha256(index_content.encode("utf-8")).hexdigest()
            generated_at = datetime.fromtimestamp(index_path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except OSError:
            pass

    def _int_metadata(key: str) -> int | None:
        try:
            return int(str(metadata.get(key, "")))
        except ValueError:
            return None

    return {
        "ok": True,
        "bundle_path": AGENT_INDEX_DIR,
        "index_path": AGENT_INDEX_PATH,
        "manifest_path": None,
        "exists": index_path.is_file(),
        "managed": bool(metadata.get("okf_version") == OKF_VERSION and _managed_index(index_path)),
        "agent_index_version": _int_metadata("zibaldone_agent_bridge_version"),
        "okf_version": metadata.get("okf_version"),
        "generated_at": generated_at,
        "note_count": _int_metadata("zibaldone_note_count") or 0,
        "index_sha256": index_hash,
    }
