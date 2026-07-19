"""Note rollback execution tests (block #7, reversible scope).

Proves the rollback mechanism on temp paths: backup-on-write, hash-verified
restore, refusal on missing backup or hash mismatch, and idempotent re-restore.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import note_rollback as R  # noqa: E402


class NoteRollbackTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="vi-rb-"))
        self.note = self.dir / "note.md"

    def test_first_write_has_no_backup(self):
        result = R.write_note_with_backup(self.note, "v1 content")
        self.assertFalse(result["rollback_available"])
        self.assertIsNone(result["backup_path"])
        self.assertEqual(self.note.read_text(), "v1 content")

    def test_overwrite_backs_up_previous_and_rollback_restores_it(self):
        first = R.write_note_with_backup(self.note, "v1 content")
        second = R.write_note_with_backup(self.note, "v2 content")
        self.assertTrue(second["rollback_available"])
        self.assertEqual(self.note.read_text(), "v2 content")
        # previous_hash recorded on the v2 write is the hash of v1
        rb = R.execute_rollback(self.note, expected_previous_hash=second["previous_hash"])
        self.assertTrue(rb["restored"])
        self.assertEqual(self.note.read_text(), "v1 content")
        self.assertEqual(rb["restored_hash"], first["current_hash"])

    def test_rollback_without_backup_raises(self):
        R.write_note_with_backup(self.note, "only version")
        with self.assertRaises(R.RollbackError):
            R.execute_rollback(self.note, expected_previous_hash="sha256:whatever")

    def test_rollback_refuses_on_hash_mismatch(self):
        R.write_note_with_backup(self.note, "v1")
        R.write_note_with_backup(self.note, "v2")
        with self.assertRaises(R.RollbackError):
            R.execute_rollback(self.note, expected_previous_hash="sha256:wrong")
        # note left untouched (still v2) when rollback is refused
        self.assertEqual(self.note.read_text(), "v2")

    def test_rollback_is_idempotent(self):
        R.write_note_with_backup(self.note, "v1")
        second = R.write_note_with_backup(self.note, "v2")
        prev = second["previous_hash"]
        R.execute_rollback(self.note, expected_previous_hash=prev)
        again = R.execute_rollback(self.note, expected_previous_hash=prev)
        self.assertTrue(again["restored"])
        self.assertEqual(self.note.read_text(), "v1")


if __name__ == "__main__":
    unittest.main()
