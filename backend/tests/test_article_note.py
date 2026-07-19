"""Article lane (M1): note shape, dedupe-update persistence, dry-run."""
import tempfile
import unittest
from pathlib import Path

from article_note import ARTICLES_SUBFOLDER, build_article_note
from news_source_to_note import source_hash
from news_vault_write import load_news_index, write_news_note
from obsidian import parse_note_fields

AI = {"explicit_topic": "主題一句", "key_points": "重點A", "terms": "Claude",
      "content_value": "對專案的價值", "source_platform": "articles", "content_category": "AI LLM"}
URL = "https://example.com/post/claude-fable-5"


class ArticleNoteShapeTests(unittest.TestCase):
    def setUp(self):
        self.note = build_article_note(url=URL, title="Fable 5 發布", content="內文段落。",
                                       ai_summary=AI, manual_summary="我的心得", author="anthropic")

    def test_note_enters_the_inbox_loop(self):
        self.assertIn("status: inbox", self.note)
        self.assertIn("source: article", self.note)
        self.assertIn(f"source_hash: {source_hash(URL)}", self.note)

    def test_note_carries_ai_block_and_body(self):
        self.assertIn("<!-- vaultwiki:ai:start -->", self.note)
        self.assertIn("## 原文", self.note)
        self.assertIn("內文段落。", self.note)
        self.assertIn("我的心得", self.note)

    def test_field_view_round_trip(self):
        fields = parse_note_fields(self.note)
        self.assertEqual(fields["title"], "Fable 5 發布")
        self.assertEqual(fields["key_points"], "重點A")
        self.assertEqual(fields["content_category"], "AI LLM")


class ReviewedStatusTests(unittest.TestCase):
    def test_reviewed_note_skips_the_inbox(self):
        import tempfile
        from pathlib import Path

        from inbox import scan_inbox
        note = build_article_note(url=URL, title="讀完即收", content="內文",
                                  ai_summary=AI, status="reviewed")
        self.assertIn("status: reviewed", note)
        self.assertIn("next_action: none", note)
        vault = Path(tempfile.mkdtemp(prefix="vi-reviewed-"))
        (vault / "02_Sources/articles").mkdir(parents=True)
        (vault / "02_Sources/articles/read.md").write_text(note, encoding="utf-8")
        self.assertEqual(scan_inbox(str(vault))["total"], 0)


class ArticlePersistTests(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp(prefix="vi-article-"))

    def _save(self, body: str):
        note = build_article_note(url=URL, title="Fable 5 發布", content=body, ai_summary=AI)
        return write_news_note(vault_path=str(self.vault), subfolder=ARTICLES_SUBFOLDER,
                               source_hash=source_hash(URL), url=URL, title="Fable 5 發布", note_markdown=note)

    def test_same_url_updates_instead_of_forking(self):
        first = self._save("v1 內文")
        second = self._save("v2 內文")
        self.assertTrue(first["created_new"])
        self.assertFalse(second["created_new"])
        self.assertEqual(first["relative_path"], second["relative_path"])
        content = (self.vault / second["relative_path"]).read_text(encoding="utf-8")
        self.assertIn("v2 內文", content)
        index = load_news_index(str(self.vault), ARTICLES_SUBFOLDER)
        self.assertEqual(len(index["items"]), 1)

    def test_note_lands_in_articles_subfolder(self):
        result = self._save("內文")
        self.assertTrue(result["relative_path"].startswith(ARTICLES_SUBFOLDER))


if __name__ == "__main__":
    unittest.main()
