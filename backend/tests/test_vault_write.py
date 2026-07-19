"""Real-vault write + rollback-backup integration tests (#1 + #2 pairing).

A create needs no backup; an overwrite (update_ai on an existing entry) backs up
the previous file first, so a #7 rollback can restore it. All against a temp
vault — no real vault, no provider.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import note_rollback as R  # noqa: E402
import vault_write as VW  # noqa: E402


def _save_kwargs(summary_topic, save_mode):
    return {
        "url": "https://www.youtube.com/watch?v=vid1",
        "title": "Vault Write Demo",
        "channel": "Demo",
        "published": None,
        "duration": None,
        "thumbnail": None,
        "transcript_en": "hello world",
        "transcript_zh": "哈囉 世界",
        "ai_summary": {"explicit_topic": summary_topic, "content_category": "AI"},
        "ai_mode": "quick",
        "manual_summary": "",
        "languages": ["en"],
        "save_mode": save_mode,
        "is_short": False,
    }


class VaultWriteTests(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp(prefix="vi-vault-"))
        self.sub = "notes/youtube"

    def _write(self, topic, save_mode):
        return VW.vault_write_with_rollback(
            vault_path=str(self.vault),
            subfolder=self.sub,
            video_id="vid1",
            save_kwargs=_save_kwargs(topic, save_mode),
        )

    def test_create_writes_note_and_indexes_without_backup(self):
        result = self._write("topic v1", "create")
        self.assertFalse(result["rollback_available"])
        self.assertIsNone(result["backup"])
        self.assertTrue(Path(result["path"]).exists())

    def test_overwrite_backs_up_and_rollback_restores_previous(self):
        first = self._write("topic v1", "create")
        original = Path(first["path"]).read_text(encoding="utf-8")
        second = self._write("topic v2 DIFFERENT", "update_ai")
        self.assertTrue(second["rollback_available"])
        self.assertIsNotNone(second["backup"])
        # the note content changed on overwrite
        self.assertNotEqual(Path(second["path"]).read_text(encoding="utf-8"), original)
        # #7 rollback restores the backed-up previous version
        rb = R.execute_rollback(second["path"], expected_previous_hash=second["backup"]["previous_hash"])
        self.assertTrue(rb["restored"])
        self.assertEqual(Path(second["path"]).read_text(encoding="utf-8"), original)


    def test_vault_rollback_restores_note_and_index_entry(self):
        from obsidian import load_index

        self._write("topic v1", "create")
        entry_v1 = load_index(str(self.vault), self.sub)["items"]["vid1"]
        hash_v1 = entry_v1["content_hash"]

        second = self._write("topic v2 DIFFERENT", "update_ai")
        entry_v2 = load_index(str(self.vault), self.sub)["items"]["vid1"]
        self.assertNotEqual(entry_v2["content_hash"], hash_v1, "overwrite changed index hash")

        result = VW.vault_rollback(
            vault_path=str(self.vault),
            subfolder=self.sub,
            video_id="vid1",
            expected_previous_hash=second["backup"]["previous_hash"],
        )
        self.assertTrue(result["restored"])
        self.assertTrue(result["index_entry_restored"], "index entry must be restored too (closes open finding)")
        entry_after = load_index(str(self.vault), self.sub)["items"]["vid1"]
        self.assertEqual(entry_after["content_hash"], hash_v1, "index entry rolled back to previous version")

    def test_vault_rollback_without_index_entry_raises(self):
        with self.assertRaises(__import__("note_rollback").RollbackError):
            VW.vault_rollback(
                vault_path=str(self.vault),
                subfolder=self.sub,
                video_id="missing",
                expected_previous_hash="sha256:x",
            )


if __name__ == "__main__":
    unittest.main()
