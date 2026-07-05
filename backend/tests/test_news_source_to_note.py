"""News source-to-note orchestrator tests (parallel render path).

Locks the contract: a news article is operator-supplied (url + optional content +
optional summary), keyed by a URL-derived source_hash (no video id), dry-run
writes nothing, a live run renders a `type: source` news note and drives the
injected writer, and the frontmatter carries the news fields (not caption fields).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import news_source_to_note as N  # noqa: E402


class _Spy:
    def __init__(self, ret):
        self.calls = 0
        self.last_args = None
        self.ret = ret

    def __call__(self, *args, **kwargs):
        self.calls += 1
        self.last_args = (args, kwargs)
        return self.ret


class NewsSourceToNoteTests(unittest.TestCase):
    def _run(self, *, url="https://example.com/a", title="Headline", content="body text",
             summary="", source_type="", dry_run=True, writer=None):
        writer = writer or _Spy({"relative_path": "news/headline.md", "created_new": True})
        result = N.run_news_source_to_note(
            url=url, title=title, content=content, summary=summary,
            source_type=source_type, writer_fn=writer, dry_run=dry_run,
            run_date="2026-06-08",
        )
        return result, writer

    def test_missing_url_stops_at_intake(self):
        result, writer = self._run(url="   ")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "missing_url")
        self.assertEqual(writer.calls, 0)

    def test_missing_title_stops_at_intake(self):
        result, writer = self._run(title="")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "missing_title")
        self.assertEqual(writer.calls, 0)

    def test_dry_run_writes_nothing(self):
        result, writer = self._run(dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["stage"], "preview")
        self.assertEqual(writer.calls, 0)
        self.assertEqual(result["source_hash"], N.source_hash("https://example.com/a"))

    def test_live_run_renders_and_writes(self):
        result, writer = self._run(dry_run=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["stage"], "written")
        self.assertEqual(writer.calls, 1)
        sid, payload = writer.last_args[0]
        self.assertEqual(sid, N.source_hash("https://example.com/a"))
        self.assertIn("note_markdown", payload)

    def test_source_hash_is_stable_and_url_keyed(self):
        a = N.source_hash("https://example.com/a")
        self.assertEqual(a, N.source_hash("https://example.com/a"))
        self.assertNotEqual(a, N.source_hash("https://example.com/b"))

    def test_frontmatter_carries_news_fields_not_caption_fields(self):
        note = N.render_news_note(
            {"url": "https://example.com/a", "title": "Headline", "content": "c", "summary": "s"},
            run_date="2026-06-08",
        )
        self.assertIn("type: source", note)
        self.assertIn("source_type: article", note)
        self.assertIn(f"source_hash: {N.source_hash('https://example.com/a')}", note)
        self.assertIn("site: example.com", note)
        self.assertIn("## Extraction Queue", note)
        self.assertNotIn("transcript_en", note)
        self.assertNotIn("video_id", note)

    def test_arxiv_url_renders_as_paper(self):
        note = N.render_news_note(
            {"url": "https://arxiv.org/abs/2401.00001", "title": "Paper"},
            run_date="2026-06-08",
        )
        self.assertIn("source: arxiv", note)
        self.assertIn("source_type: paper", note)

    def test_hostname_strips_www(self):
        self.assertEqual(N.hostname("https://www.example.com/x"), "example.com")


if __name__ == "__main__":
    unittest.main()
