"""News vault writer tests (real-vault write keyed by source_hash, with rollback).

Uses a temp vault. Locks: a new URL creates a note + index entry keyed by
source_hash, re-intaking the same URL updates the SAME note (backup available),
and the relative_path stays under the news subfolder.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import news_source_to_note as N  # noqa: E402
import news_vault_write as W  # noqa: E402


class NewsVaultWriteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = self._tmp.name
        self.sub = "note_study/02_Sources/news"

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, url="https://example.com/a", title="Headline", body="content v1"):
        sid = N.source_hash(url)
        note = N.render_news_note({"url": url, "title": title, "content": body}, run_date="2026-06-09")
        return W.write_news_note(
            vault_path=self.vault, subfolder=self.sub, source_hash=sid,
            url=url, title=title, note_markdown=note,
        ), sid

    def test_new_url_creates_note_and_index_entry(self):
        result, sid = self._write()
        self.assertTrue(result["created_new"])
        self.assertFalse(result["rollback_available"])
        self.assertTrue(result["relative_path"].startswith(self.sub))
        note_abs = Path(self.vault) / result["relative_path"]
        self.assertTrue(note_abs.exists())
        index = W.load_news_index(self.vault, self.sub)
        self.assertIn(sid, index["items"])
        self.assertEqual(index["items"][sid]["note_path"], result["relative_path"])

    def test_reintake_same_url_updates_same_note_with_backup(self):
        first, sid = self._write(body="content v1")
        second, sid2 = self._write(body="content v2")
        self.assertEqual(sid, sid2)
        self.assertEqual(first["relative_path"], second["relative_path"])  # same note, not forked
        self.assertFalse(second["created_new"])
        self.assertTrue(second["rollback_available"])  # overwrite backed up
        note_abs = Path(self.vault) / second["relative_path"]
        self.assertIn("content v2", note_abs.read_text(encoding="utf-8"))
        index = W.load_news_index(self.vault, self.sub)
        self.assertEqual(len(index["items"]), 1)  # one source, one entry

    def test_distinct_urls_make_distinct_notes(self):
        a, _ = self._write(url="https://example.com/a", title="A")
        b, _ = self._write(url="https://example.com/b", title="B")
        self.assertNotEqual(a["relative_path"], b["relative_path"])
        index = W.load_news_index(self.vault, self.sub)
        self.assertEqual(len(index["items"]), 2)


if __name__ == "__main__":
    unittest.main()
