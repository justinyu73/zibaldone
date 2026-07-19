"""手機收錄通道：01_Inbox 掃描抽網址、影片/文章判別、去重、忽略永久化、檔案不動。"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ["YT_NOTE_APP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="vi-capture-cfg-")

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capture_inbox import dismiss, scan_capture_inbox  # noqa: E402


class CaptureInboxTests(unittest.TestCase):
    def setUp(self):
        os.environ["YT_NOTE_APP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="vi-capture-cfg-")
        self.root = Path(tempfile.mkdtemp(prefix="vi-capture-vault-"))
        self.inbox = self.root / "01_Inbox"
        self.inbox.mkdir()

    def test_scan_extracts_urls_with_kind_and_dedup(self):
        (self.inbox / "phone.md").write_text(
            "看這個 https://youtu.be/abc123 很讚\n"
            "文章 https://example.com/post\n"
            "重複 https://example.com/post\n",
            encoding="utf-8",
        )
        (self.inbox / "memo.txt").write_text("https://www.youtube.com/watch?v=xyz", encoding="utf-8")
        (self.inbox / "image.png").write_bytes(b"\x89PNG")
        result = scan_capture_inbox(str(self.root))
        urls = {i["url"]: i["kind"] for i in result["items"]}
        self.assertEqual(result["total"], 3)
        self.assertEqual(urls["https://youtu.be/abc123"], "video")
        self.assertEqual(urls["https://example.com/post"], "article")
        self.assertEqual(urls["https://www.youtube.com/watch?v=xyz"], "video")

    def test_dismiss_is_permanent_and_file_untouched(self):
        note = self.inbox / "phone.md"
        original = "https://example.com/keep\n"
        note.write_text(original, encoding="utf-8")
        first = scan_capture_inbox(str(self.root))
        dismiss([first["items"][0]["id"]])
        again = scan_capture_inbox(str(self.root))
        self.assertEqual(again["total"], 0)
        self.assertEqual(note.read_text(encoding="utf-8"), original)

    def test_missing_inbox_folder_returns_empty(self):
        empty_root = Path(tempfile.mkdtemp(prefix="vi-capture-none-"))
        self.assertEqual(scan_capture_inbox(str(empty_root))["total"], 0)


if __name__ == "__main__":
    unittest.main()
