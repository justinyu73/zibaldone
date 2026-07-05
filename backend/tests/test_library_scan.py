"""Scoped folder-scan for the media library: surface the app's SOURCE notes
(video / news, marked `type: source`) that the _youtube_index.json misses, while
intentionally skipping arbitrary Obsidian markdown (not a global .md scan).
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_state import AppStateRuntime, scan_folder_md_records  # noqa: E402


def _mkfolder():
    d = Path(tempfile.mkdtemp(prefix="vi-scan-"))
    (d / "videos").mkdir()
    (d / "videos" / "video.md").write_text(
        "---\ntype: source\nsource: youtube\nsource_type: video\n"
        "url: \"https://youtu.be/x\"\ntitle: A Video Note\n分類：AI LLM\n---\nbody\n",
        encoding="utf-8",
    )
    (d / "news.md").write_text(
        "---\ntype: source\nsource: news\nsource_type: news\ntitle: A News Note\n---\nbody\n",
        encoding="utf-8",
    )
    # Plain Obsidian markdown — no source marker; must be skipped.
    (d / "diary.md").write_text("# My Private Diary\nnot a source note\n", encoding="utf-8")
    return d


class FolderScanTests(unittest.TestCase):
    def test_includes_source_notes_skips_plain_markdown(self):
        recs = scan_folder_md_records(_mkfolder(), indexed_paths=set())
        titles = {r["title"] for r in recs}
        self.assertIn("A Video Note", titles)
        self.assertIn("A News Note", titles)
        self.assertNotIn("My Private Diary", titles)  # plain md is not scanned

    def test_indexed_paths_are_not_duplicated(self):
        d = _mkfolder()
        first = scan_folder_md_records(d, indexed_paths=set())
        already = {first[0]["path"]}
        second = scan_folder_md_records(d, indexed_paths=already)
        self.assertNotIn(first[0]["path"], {r["path"] for r in second})
        self.assertEqual(len(second), len(first) - 1)

    def test_read_model_surfaces_unindexed_source_notes(self):
        d = _mkfolder()  # no _youtube_index.json at all
        view = AppStateRuntime.local_library_read_model_for_workspace(
            str(d), index_path="_youtube_index.json"
        )
        titles = {r["title"] for r in view["read_model"]["records"]}
        self.assertIn("A Video Note", titles)
        self.assertIn("A News Note", titles)
        self.assertNotIn("My Private Diary", titles)


if __name__ == "__main__":
    unittest.main()
