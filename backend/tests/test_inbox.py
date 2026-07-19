"""Inbox digestion: scan / mark-reviewed / trash (merge IA #7)."""
import tempfile
import unittest
from pathlib import Path

from inbox import mark_reviewed, scan_inbox, trash_note

NOTE_INBOX = """---
type: source
title: "待消化筆記"
status: inbox
next_action: review
updated: 2026-06-01
---

# 待消化筆記

本文內容不可被動作改動。
"""

NOTE_PROCESSED = NOTE_INBOX.replace("status: inbox", "status: processed")
NOTE_NO_STATUS = "---\ntype: source\ntitle: \"無狀態速記\"\n---\n\n速記內容。\n"


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="vi-inbox-"))
        (self.root / "01_Inbox/manual-intake").mkdir(parents=True)
        (self.root / "02_Sources/youtube").mkdir(parents=True)
        (self.root / "01_Inbox/manual-intake/a_inbox.md").write_text(NOTE_INBOX, encoding="utf-8")
        (self.root / "01_Inbox/manual-intake/b_done.md").write_text(NOTE_PROCESSED, encoding="utf-8")
        (self.root / "01_Inbox/quick.md").write_text(NOTE_NO_STATUS, encoding="utf-8")
        (self.root / "01_Inbox/_README.md").write_text("---\ntype: readme\n---\n", encoding="utf-8")
        (self.root / "02_Sources/youtube/yt_inbox.md").write_text(NOTE_INBOX, encoding="utf-8")
        (self.root / "02_Sources/youtube/yt_done.md").write_text(NOTE_PROCESSED, encoding="utf-8")

    def test_scan_lists_inbox_and_statusless_inbox_notes_only(self):
        result = scan_inbox(str(self.root))
        paths = sorted(item["path"] for item in result["items"])
        self.assertEqual(paths, [
            "01_Inbox/manual-intake/a_inbox.md",
            "01_Inbox/quick.md",
            "02_Sources/youtube/yt_inbox.md",
        ])
        self.assertEqual(result["total"], 3)

    def test_scan_missing_root_returns_empty(self):
        self.assertEqual(scan_inbox(str(self.root / "nope")), {"items": [], "total": 0})

    def test_mark_reviewed_touches_frontmatter_only(self):
        rel = "02_Sources/youtube/yt_inbox.md"
        result = mark_reviewed(str(self.root), rel)
        self.assertEqual(result["status"], "reviewed")
        content = (self.root / rel).read_text(encoding="utf-8")
        self.assertIn("status: reviewed", content)
        self.assertIn("next_action: none", content)
        self.assertIn("本文內容不可被動作改動。", content)
        self.assertNotIn("status: inbox", content)

    def test_mark_reviewed_requires_inbox_status(self):
        with self.assertRaises(ValueError):
            mark_reviewed(str(self.root), "02_Sources/youtube/yt_done.md")

    def test_mark_reviewed_rejects_traversal(self):
        from app_state import AppStateError
        with self.assertRaises(AppStateError):
            mark_reviewed(str(self.root), "../outside.md")

    def test_trash_moves_into_vault_trash(self):
        rel = "01_Inbox/quick.md"
        result = trash_note(str(self.root), rel)
        self.assertFalse((self.root / rel).exists())
        trashed = self.root / result["trashed_to"]
        self.assertTrue(trashed.exists())
        self.assertTrue(result["trashed_to"].startswith("_trash/"))
        self.assertIn("速記內容", trashed.read_text(encoding="utf-8"))

    def test_trash_avoids_name_collision(self):
        first = trash_note(str(self.root), "01_Inbox/manual-intake/a_inbox.md")
        (self.root / "01_Inbox/manual-intake/a_inbox.md").write_text(NOTE_INBOX, encoding="utf-8")
        second = trash_note(str(self.root), "01_Inbox/manual-intake/a_inbox.md")
        self.assertNotEqual(first["trashed_to"], second["trashed_to"])


if __name__ == "__main__":
    unittest.main()
