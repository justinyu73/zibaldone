"""Article URL → standard source note（文章×雷達整合 M1，人工 lane）.

Fetches the article body (trafilatura; paste fallback lives in the UI) and
renders the SAME note shape as video notes — frontmatter `status: inbox` +
the vaultwiki AI block — so the inbox / reading view / field view / full-text
search / digestion loop all apply with zero new concepts. Persistence reuses
the news writer (source_hash dedupe + backup + own index).
"""
from __future__ import annotations

import json
from typing import Any

from news_source_to_note import hostname, source_hash
from obsidian import _ai_learning_block, _dump_frontmatter, now_date, now_stamp

ARTICLES_SUBFOLDER = "02_Sources/articles"


def fetch_article(url: str) -> dict[str, Any]:
    """Fetch + extract main text/metadata. Network errors and extraction misses
    return ok=False with a reason — the UI then offers the paste-mode fallback."""
    import trafilatura

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return {"ok": False, "reason": "fetch_failed", "message": "無法下載此網址（可能需登入或被擋），請改用「貼上內文」"}
    extracted = trafilatura.extract(downloaded, output_format="json", with_metadata=True, include_comments=False)
    if not extracted:
        return {"ok": False, "reason": "extract_failed", "message": "抓到頁面但抽不出正文（可能是 JS 渲染頁），請改用「貼上內文」"}
    data = json.loads(extracted)
    return {
        "ok": True,
        "title": str(data.get("title") or "").strip(),
        "text": str(data.get("text") or "").strip(),
        "author": str(data.get("author") or "").strip(),
        "date": str(data.get("date") or "").strip(),
        "site": hostname(url),
        "source_hash": source_hash(url),
    }


def build_article_note(
    *,
    url: str,
    title: str,
    content: str,
    ai_summary: dict[str, str],
    ai_mode: str = "quick",
    manual_summary: str = "",
    author: str = "",
    published: str = "",
    status: str = "inbox",
) -> str:
    """status: inbox（收了還沒讀→進收件匣）或 reviewed（雷達就地讀完收藏，
    不再進收件匣重複消化——新聞台模式）。"""
    today = now_date()
    site = hostname(url)
    frontmatter = _dump_frontmatter({
        "type": "source",
        "source": "article",
        "source_type": "article",
        "url": url,
        "canonical_url": url,
        "source_hash": source_hash(url),
        "title": title,
        "author": author or None,
        "site": site,
        "posted_at": published or None,
        "clipped_at": now_stamp(),
        "status": status,
        "next_action": "review" if status == "inbox" else "none",
        "created": today,
        "updated": today,
        "lifecycle": "active",
        "summary": (ai_summary.get("key_points") or manual_summary or "").replace("\n", " ")[:220],
        "tags": ["type/source", "source/article", f"status/{status}"],
    })
    body = [
        frontmatter,
        "",
        f"# {title}",
        "",
        "> [!info] 來源資訊",
        f"> - 連結：[{site}]({url})",
    ]
    if author:
        body.append(f"> - 作者：{author}")
    if published:
        body.append(f"> - 發布：{published}")
    body.extend([
        "",
        _ai_learning_block(ai_summary, ai_mode),
        "",
        "## 個人心得筆記",
        "",
        manual_summary.strip() if manual_summary.strip() else "- ",
        "",
        "## 原文",
        "",
        content.strip() if content.strip() else "（未保留原文）",
        "",
        "---",
        f"*saved at {now_stamp()}*",
    ])
    return "\n".join(body) + "\n"
