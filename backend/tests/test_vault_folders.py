"""Vault-root folder listing for the value library's default aggregation."""
import tempfile
import unittest
from pathlib import Path

from app_state import list_source_subfolders


class ListSourceSubfoldersTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="vi-vroot-"))
        sources = self.root / "02_Sources"
        for name in ("youtube", "daily", "github", "_attachments", ".hidden"):
            (sources / name).mkdir(parents=True)
        (sources / "stray.md").write_text("x", encoding="utf-8")

    def test_lists_visible_source_dirs_sorted(self):
        folders = list_source_subfolders(str(self.root))
        self.assertEqual([f["name"] for f in folders], ["daily", "github", "youtube"])
        for folder in folders:
            self.assertTrue(folder["path"].endswith(f"02_Sources/{folder['name']}"))

    def test_missing_sources_dir_returns_empty(self):
        self.assertEqual(list_source_subfolders(str(self.root / "nope")), [])
        self.assertEqual(list_source_subfolders(""), [])


if __name__ == "__main__":
    unittest.main()
