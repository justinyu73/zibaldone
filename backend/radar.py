"""資訊雷達（M2）：手動掃描 HN / GitHub 新專案 / RSS → 候選清單。

設計紀律（article_radar_integration_design_2026-06-12）：
- 自動抓的是「候選」，存 app 資料區（radar.json），裁決前不進 vault
- 指紋永久去重：忽略過/採用過的網址永不再出現
- 單次掃描上限（預設每源 20、總 50，可由設定調參）；只有手動「刷新」觸發，無排程
- GitHub 只看「近 90 天內建立」的新專案，排除老專案維護假訊號
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree

from news_source_to_note import hostname, source_hash

PER_SOURCE_CAP = 20
TOTAL_CAP = 50
HN_MIN_POINTS = 80
GH_MIN_STARS = 150
GH_MAX_AGE_DAYS = 90
RSS_MAX_AGE_DAYS = 7

AI_KEYWORDS = (
    "ai", "llm", "gpt", "claude", "gemini", "openai", "anthropic", "deepmind",
    "agent", "model", "transformer", "rag", "inference", "fine-tun", "prompt",
    "machine learning", "neural", "diffusion",
)
IMPORTANT_PATTERN = re.compile(r"(announc|releas|launch|introduc|unveil|发布|發布|推出)", re.I)

DEFAULT_FEEDS = [
    "https://openai.com/news/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://huggingface.co/blog/feed.xml",
    "https://simonwillison.net/atom/everything/",
]

# 使用者可調參數（設定頁雷達區塊）；keywords 留空＝內建 AI 詞庫，
# 自訂時影響 HN 標題過濾與 GitHub 搜尋/過濾（RSS 是人工精選來源，不套主題過濾）。
DEFAULT_TUNING = {
    "total_cap": TOTAL_CAP,
    "per_source_cap": PER_SOURCE_CAP,
    "hn_min_points": HN_MIN_POINTS,
    "gh_min_stars": GH_MIN_STARS,
    "keywords": [],
    "enable_hn": True,
    "enable_github": True,
    "enable_rss": True,
}


def _normalize_tuning(tuning: dict[str, Any] | None) -> dict[str, Any]:
    merged = {**DEFAULT_TUNING, **(tuning or {})}
    for key in ("total_cap", "per_source_cap"):
        try:
            merged[key] = max(1, int(merged[key]))
        except (TypeError, ValueError):
            merged[key] = DEFAULT_TUNING[key]
    for key in ("hn_min_points", "gh_min_stars"):
        try:
            merged[key] = max(0, int(merged[key]))
        except (TypeError, ValueError):
            merged[key] = DEFAULT_TUNING[key]
    merged["keywords"] = [str(k).strip().lower() for k in (merged.get("keywords") or []) if str(k).strip()]
    for key in ("enable_hn", "enable_github", "enable_rss"):
        merged[key] = bool(merged[key])
    return merged


def _radar_path() -> Path:
    base = Path(os.getenv("YT_NOTE_APP_CONFIG_DIR", str(Path.home() / ".config" / "yt-note-app")))
    base.mkdir(parents=True, exist_ok=True)
    return base / "radar.json"


def _load_state() -> dict[str, Any]:
    path = _radar_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("seen", {})
    data.setdefault("candidates", [])
    return data


def _save_state(data: dict[str, Any]) -> None:
    path = _radar_path()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


_SSL_CONTEXT = None


def _ssl_context():
    """PyInstaller-frozen macOS Python can't find system CA certs; use certifi's
    bundle (already shipped as a trafilatura dependency)."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        import ssl

        import certifi

        _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
    return _SSL_CONTEXT


def _http(url: str, accept: str = "application/json") -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "yt-note-app-radar", "Accept": accept})
    with urllib.request.urlopen(request, timeout=20, context=_ssl_context()) as response:
        return response.read()


def _ai_related(text: str, keywords: list[str] | None = None) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in (keywords or AI_KEYWORDS))


def _fresh(date_text: str, max_age_days: int) -> bool:
    """Tolerant freshness check: unparsable dates pass (curated low-volume feeds)."""
    text = (date_text or "").strip()
    if not text:
        return True
    parsed = None
    try:
        parsed = parsedate_to_datetime(text)  # RFC822 (RSS2)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))  # ISO (Atom)
        except ValueError:
            return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed >= datetime.now(timezone.utc) - timedelta(days=max_age_days)


def fetch_hackernews(min_points: int = HN_MIN_POINTS, keywords: list[str] | None = None) -> list[dict[str, Any]]:
    raw = json.loads(_http("https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"))
    items: list[dict[str, Any]] = []
    for hit in raw.get("hits", []):
        title = str(hit.get("title") or "")
        url = str(hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}")
        points = int(hit.get("points") or 0)
        comments = int(hit.get("num_comments") or 0)
        if points < min_points or not _ai_related(title, keywords):
            continue
        items.append({"title": title, "url": url, "source": "hackernews", "heat": f"{points} pts · {comments} 留言"})
    return items


def fetch_github_new_repos(min_stars: int = GH_MIN_STARS, keywords: list[str] | None = None) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=GH_MAX_AGE_DAYS)).strftime("%Y-%m-%d")
    # GitHub 搜尋詞以第一個自訂關鍵詞為主（多詞=AND 會過窄），其餘靠結果端過濾
    topic = (keywords or ["ai"])[0]
    query = urllib.parse.quote(f"created:>{since} stars:>{min_stars} {topic}")
    raw = json.loads(_http(f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page=20"))
    items: list[dict[str, Any]] = []
    for repo in raw.get("items", []):
        description = str(repo.get("description") or "")
        name = str(repo.get("full_name") or "")
        if keywords and not _ai_related(f"{name} {description}", keywords):
            continue
        items.append({
            "title": f"{name}：{description[:80]}" if description else name,
            "url": str(repo.get("html_url") or ""),
            "source": "github",
            "heat": f"★{repo.get('stargazers_count', 0)}・{GH_MAX_AGE_DAYS}天內新專案",
        })
    return items


def parse_feed(xml_bytes: bytes, feed_url: str) -> list[dict[str, Any]]:
    """Tolerant RSS2/Atom parsing with stdlib（不引入 feedparser 依賴）."""
    root = ElementTree.fromstring(xml_bytes)
    site = hostname(feed_url)
    atom = "{http://www.w3.org/2005/Atom}"
    items: list[dict[str, Any]] = []
    for item in root.iter("item"):  # RSS2
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        if title and link and _fresh(published, RSS_MAX_AGE_DAYS):
            items.append({"title": title, "url": link, "source": site, "heat": published[:16] or "RSS"})
    for entry in root.iter(f"{atom}entry"):  # Atom
        title = (entry.findtext(f"{atom}title") or "").strip()
        link_el = entry.find(f"{atom}link")
        link = (link_el.get("href") if link_el is not None else "") or ""
        updated = (entry.findtext(f"{atom}updated") or "").strip()
        if title and link and _fresh(updated, RSS_MAX_AGE_DAYS):
            items.append({"title": title, "url": link, "source": site, "heat": updated[:10] or "RSS"})
    return items


def _fetch_feed(feed_url: str) -> list[dict[str, Any]]:
    return parse_feed(_http(feed_url, "application/xml, text/xml, */*"), feed_url)


def scan(
    feeds: list[str] | None = None,
    fetchers: list[tuple[str, Callable[[], list[dict[str, Any]]]]] | None = None,
    tuning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    t = _normalize_tuning(tuning)
    feed_urls = [f.strip() for f in (feeds or []) if f.strip()] or DEFAULT_FEEDS
    if fetchers is None:
        fetchers = []
        if t["enable_hn"]:
            fetchers.append(("hackernews", lambda: fetch_hackernews(t["hn_min_points"], t["keywords"])))
        if t["enable_github"]:
            fetchers.append(("github", lambda: fetch_github_new_repos(t["gh_min_stars"], t["keywords"])))
        if t["enable_rss"]:
            fetchers += [(hostname(u), (lambda url=u: _fetch_feed(url))) for u in feed_urls]
    state = _load_state()
    seen = state["seen"]
    existing_ids = {c["id"] for c in state["candidates"]}
    added: list[dict[str, Any]] = []
    errors: list[str] = []
    for name, fetch in fetchers:
        try:
            items = fetch()
        except Exception as exc:  # noqa: BLE001 - one dead source must not kill the scan
            errors.append(f"{name}: {exc}")
            continue
        count = 0
        for item in items:
            if count >= t["per_source_cap"] or len(added) >= t["total_cap"]:
                break
            url = str(item.get("url") or "")
            if not url:
                continue
            candidate_id = source_hash(url)
            if candidate_id in seen or candidate_id in existing_ids:
                continue
            added.append({
                "id": candidate_id,
                "title": str(item.get("title") or url)[:160],
                "url": url,
                "source": str(item.get("source") or name),
                "heat": str(item.get("heat") or ""),
                "important": bool(IMPORTANT_PATTERN.search(str(item.get("title") or ""))),
                "found_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            existing_ids.add(candidate_id)
            count += 1
    state["candidates"].extend(added)
    state["candidates"].sort(key=lambda c: c.get("found_at", ""), reverse=True)
    state["candidates"].sort(key=lambda c: not c.get("important", False))
    _save_state(state)
    return {"added": len(added), "total": len(state["candidates"]), "errors": errors}


def list_candidates() -> dict[str, Any]:
    state = _load_state()
    return {"candidates": state["candidates"], "total": len(state["candidates"])}


def dismiss(ids: list[str]) -> dict[str, Any]:
    """忽略/採用後移出清單，並永久記入指紋（rescan 不再出現）."""
    state = _load_state()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    id_set = {str(i) for i in ids}
    for candidate_id in id_set:
        state["seen"][candidate_id] = stamp
    state["candidates"] = [c for c in state["candidates"] if c["id"] not in id_set]
    _save_state(state)
    return {"ok": True, "total": len(state["candidates"])}
