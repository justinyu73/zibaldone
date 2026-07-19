"""Vault full-text search: FTS5 trigram index, incremental refresh, CJK queries."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("YT_NOTE_APP_CONFIG_DIR", tempfile.mkdtemp(prefix="vi-cfg-"))

import search_index
from search_index import refresh_index, search_notes


class SearchIndexTests(unittest.TestCase):
    def setUp(self):
        # Isolated config dir per test → isolated index db.
        self._cfg = tempfile.mkdtemp(prefix="vi-cfg-")
        os.environ["YT_NOTE_APP_CONFIG_DIR"] = self._cfg
        self.root = Path(tempfile.mkdtemp(prefix="vi-search-"))
        (self.root / "02_Sources/youtube").mkdir(parents=True)
        (self.root / "01_Inbox").mkdir(parents=True)
        (self.root / "02_Sources/youtube/a.md").write_text(
            "---\ntitle: \"Claude 教學\"\n---\n\n# Claude 教學\n\n全文搜尋功能的測試內容。\n",
            encoding="utf-8",
        )
        (self.root / "01_Inbox/b.md").write_text(
            "---\ntitle: \"速記\"\n---\n\n提到 prompt engineering 的段落。\n", encoding="utf-8"
        )

    def test_cjk_substring_match_with_snippet(self):
        result = search_notes(str(self.root), "搜尋功能")
        self.assertEqual(result["total"], 1)
        record = result["records"][0]
        self.assertEqual(record["path"], "02_Sources/youtube/a.md")
        self.assertEqual(record["source"], "youtube")
        self.assertIn("搜尋功能", record["snippet"].replace("[", "").replace("]", ""))

    def test_ascii_match(self):
        result = search_notes(str(self.root), "prompt engineering")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["path"], "01_Inbox/b.md")

    def test_short_two_char_query_falls_back_to_like(self):
        result = search_notes(str(self.root), "速記")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["path"], "01_Inbox/b.md")

    def test_incremental_refresh_picks_up_edit_and_delete(self):
        refresh_index(str(self.root))
        note = self.root / "02_Sources/youtube/a.md"
        note.write_text("---\ntitle: \"Claude 教學\"\n---\n\n改寫後的獨特關鍵詞句。\n", encoding="utf-8")
        os.utime(note, (note.stat().st_atime, note.stat().st_mtime + 5))
        self.assertEqual(search_notes(str(self.root), "獨特關鍵詞")["total"], 1)
        self.assertEqual(search_notes(str(self.root), "搜尋功能")["total"], 0)
        note.unlink()
        self.assertEqual(search_notes(str(self.root), "獨特關鍵詞")["total"], 0)

    def test_no_query_or_missing_root_is_empty(self):
        self.assertEqual(search_notes(str(self.root), "")["total"], 0)
        self.assertEqual(search_notes(str(self.root / "nope"), "x")["total"], 0)

    def test_index_db_lives_outside_the_vault(self):
        search_notes(str(self.root), "搜尋")
        vault_files = [p.name for p in self.root.rglob("*.sqlite*")]
        self.assertEqual(vault_files, [])


if __name__ == "__main__":
    unittest.main()
