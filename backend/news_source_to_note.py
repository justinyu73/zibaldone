"""News source-to-note orchestrator — a parallel render path to the caption
pipeline (`source_to_note`).

A news article is operator-supplied: a URL plus optional pasted content and an
optional manual summary. It has no video id, no captions, and no EN->ZH
translation, so it does NOT fit the caption orchestrator. This module renders a
`type: source` news note (frontmatter + extraction-queue body) and writes it via
an injected writer, keyed by a URL-derived `source_hash` instead of a video id.

External effects (the write) are injected, so the orchestration — dedup by
source_hash, dry-run skips the write — is fully testable with stubs.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable
from urllib.parse import urlparse

from obsidian import _dump_frontmatter, now_date

# writer_fn(source_hash, payload) -> {"relative_path", "created_new", ...}
WriterFn = Callable[[str, dict[str, Any]], dict[str, Any]]


def source_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def hostname(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def canonical_source_fields(url: str, source_type: str) -> tuple[str, str, list[str]]:
    """(source_kind, source_type, tags) — arxiv papers vs generic articles."""
    if source_type.lower() == "arxiv" or "arxiv.org" in url:
        return "arxiv", "paper", ["type/source", "source/arxiv", "status/processing"]
    return "articles", "article", ["type/source", "source/articles", "status/processing"]


def render_news_note(item: dict[str, Any], run_date: str | None = None) -> str:
    run_date = run_date or now_date()
    url = str(item.get("url") or "")
    title = str(item.get("title") or "Untitled News Source").strip()
    content = str(item.get("content") or "").strip()
    summary = str(item.get("summary") or "").strip()
    source_kind, source_type, tags = canonical_source_fields(url, str(item.get("source_type") or ""))
    site = hostname(url)
    frontmatter = _dump_frontmatter(
        {
            "type": "source",
            "source": source_kind,
            "source_type": source_type,
            "url": url,
            "source_hash": source_hash(url),
            "title": title,
            "site": site,
            "posted_at": str(item.get("posted_at") or run_date),
            "clipped_at": run_date,
            "status": "processing",
            "next_action": "atomic-extract",
            "summary": summary,
            "created": run_date,
            "updated": run_date,
            "tags": tags,
        }
    )
    body = [
        "",
        f"# {title}",
        "",
        "## Source",
        "",
        f"- URL: {url}",
        f"- Site: {site}",
        f"- Clipped: {run_date}",
        "",
        "## Summary",
        "",
        summary or "_(no operator summary)_",
        "",
        "## Content",
        "",
        content or "_(URL-only clip; no pasted content)_",
        "",
        "## Extraction Queue",
        "",
        "- [ ] Extract atomic notes",
        "- [ ] Add backlinks to relevant theme notes",
        "- [ ] Decide whether this source should remain active after extraction",
        "",
    ]
    return frontmatter + "\n".join(body)


def run_news_source_to_note(
    *,
    url: str,
    title: str,
    content: str = "",
    summary: str = "",
    source_type: str = "",
    writer_fn: WriterFn,
    dry_run: bool = True,
    run_date: str | None = None,
) -> dict[str, Any]:
    url = url.strip()
    title = title.strip()
    if not url:
        return {"ok": False, "stage": "intake", "reason": "missing_url"}
    if not title:
        return {"ok": False, "stage": "intake", "reason": "missing_title"}

    sid = source_hash(url)
    item = {
        "url": url,
        "title": title,
        "content": content,
        "summary": summary,
        "source_type": source_type,
    }
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "stage": "preview",
            "source_hash": sid,
            "title": title,
            "would_write": True,
        }

    note = render_news_note(item, run_date=run_date)
    write = writer_fn(sid, {"url": url, "title": title, "note_markdown": note})
    return {
        "ok": True,
        "dry_run": False,
        "stage": "written",
        "source_hash": sid,
        "title": title,
        "write": write,
    }
