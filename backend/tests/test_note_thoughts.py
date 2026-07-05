"""事後補心得：追加進個人心得段尾（不覆蓋）、無段落筆記補段、備份存在。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from note_thoughts import SECTION, append_thought  # noqa: E402

YT_NOTE = """---
title: t
---

## AI 學習筆記

- 點

## 個人心得筆記

- 原本的心得

## 逐字稿

body
"""

MEETING_NOTE = """## 摘要
x

## 逐字稿
y
"""


class AppendThoughtTests(unittest.TestCase):
    def _write(self, content):
        path = Path(tempfile.mkdtemp(prefix="vi-thought-")) / "note.md"
        path.write_text(content, encoding="utf-8")
        return path

    def test_appends_dated_callout_inside_section_keeping_existing(self):
        path = self._write(YT_NOTE)
        result = append_thought(path, "新的想法\n第二行")
        text = path.read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertIn("- 原本的心得", text)
        self.assertIn(f"> [!note] {result['stamp']} 補心得", text)
        self.assertIn("> 新的想法", text)
        self.assertIn("> 第二行", text)
        # block lands before the next section, not after the transcript
        self.assertLess(text.index("補心得"), text.index("## 逐字稿"))
        self.assertGreater(text.index("補心得"), text.index("- 原本的心得"))

    def test_note_without_section_gets_one_appended(self):
        path = self._write(MEETING_NOTE)
        append_thought(path, "會後想法")
        text = path.read_text(encoding="utf-8")
        self.assertIn(SECTION, text)
        self.assertIn("> 會後想法", text)
        self.assertGreater(text.index(SECTION), text.index("## 逐字稿"))

    def test_distill_marker_upserted_into_frontmatter_idempotently(self):
        path = self._write(YT_NOTE)
        append_thought(path, "a", distill=True)
        append_thought(path, "b", distill=True)
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count("distill: candidate"), 1)
        self.assertLess(text.index("distill: candidate"), text.index("## AI 學習筆記"))

    def test_distill_creates_frontmatter_when_absent(self):
        path = self._write(MEETING_NOTE)
        append_thought(path, "x", distill=True)
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\ndistill: candidate\n---\n"))

    def test_backup_written_before_change(self):
        path = self._write(YT_NOTE)
        result = append_thought(path, "x")
        self.assertTrue(result.get("backup_path"))
        self.assertEqual(Path(result["backup_path"]).read_text(encoding="utf-8"), YT_NOTE)


if __name__ == "__main__":
    unittest.main()
