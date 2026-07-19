"""Language compatibility: OpenCC s2twp, CJK chunking, CJK slugs, quoted titles."""
import unittest

from services.library import _to_traditional_text
from obsidian import parse_note_fields, slugify
from translator import MAX_CHARS_PER_REQ, _chunk


class ToTraditionalTests(unittest.TestCase):
    def test_simplified_converts_with_taiwan_phrasing(self):
        self.assertEqual(_to_traditional_text("视频笔记的内容"), "影片筆記的內容")
        self.assertEqual(_to_traditional_text("软件设计问题"), "軟體設計問題")

    def test_empty_and_traditional_pass_through(self):
        self.assertEqual(_to_traditional_text(""), "")
        self.assertEqual(_to_traditional_text("已經是繁體"), "已經是繁體")


class ChunkCjkTests(unittest.TestCase):
    def test_unspaced_cjk_is_hard_split(self):
        text = "字" * (MAX_CHARS_PER_REQ * 2 + 100)
        chunks = _chunk(text)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(len(c) <= MAX_CHARS_PER_REQ for c in chunks))
        self.assertEqual("".join(chunks), text)

    def test_spaced_text_unchanged_behavior(self):
        self.assertEqual(_chunk("hello world"), ["hello world"])


class SlugifyCjkTests(unittest.TestCase):
    def test_chinese_title_keeps_meaning(self):
        slug = slugify("建立你的 AI 第二大腦")
        self.assertIn("第二大腦", slug)
        self.assertNotEqual(slug, "youtube-video")

    def test_ascii_title_unchanged(self):
        self.assertEqual(slugify("Claude Code Tutorial"), "claude-code-tutorial")

    def test_symbol_only_title_falls_back(self):
        self.assertEqual(slugify("!!!???"), "youtube-video")


class QuotedTitleTests(unittest.TestCase):
    def test_quoted_frontmatter_title_round_trips_without_quotes(self):
        content = '---\ntitle: "AI: How \\"it\\" works"\n---\n'
        self.assertEqual(parse_note_fields(content)["title"], 'AI: How "it" works')

    def test_plain_title_unchanged(self):
        self.assertEqual(parse_note_fields("---\ntitle: 普通標題\n---\n")["title"], "普通標題")


if __name__ == "__main__":
    unittest.main()
