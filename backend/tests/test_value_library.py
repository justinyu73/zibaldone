"""V1 cross-source value library: aggregate notes across an allowlist of folders
(YT / atomic / github / daily / manual), newest-first, grouped by source, skipping
index files. Read-only — folder-based inclusion, not a type filter or global scan.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_state import aggregate_value_notes  # noqa: E402


def _mkfolders():
    base = Path(tempfile.mkdtemp(prefix="vi-value-"))
    yt = base / "youtube"; yt.mkdir()
    atomic = base / "03_Atomic_Notes"; atomic.mkdir()
    (yt / "old.md").write_text("---\ntitle: Old Video\nclipped_at: \"2026-01-01\"\n---\n", encoding="utf-8")
    (yt / "new.md").write_text("---\ntitle: New Video\nclipped_at: \"2026-06-01\"\n---\n", encoding="utf-8")
    (yt / "_index.md").write_text("---\ntype: index\ntitle: Should Skip\n---\n", encoding="utf-8")
    (atomic / "note.md").write_text("---\ntype: readme\ndate: 2026-03-01\ntitle: Atomic Idea\n---\n", encoding="utf-8")
    return base, yt, atomic


class ValueLibraryTests(unittest.TestCase):
    def test_aggregates_groups_and_sorts_newest_first(self):
        base, yt, atomic = _mkfolders()
        out = aggregate_value_notes([str(yt), str(atomic)])
        titles = [r["title"] for r in out["records"]]
        self.assertIn("New Video", titles)
        self.assertIn("Atomic Idea", titles)
        self.assertNotIn("Should Skip", titles)            # type: index skipped
        self.assertEqual(out["sources"], {"youtube": 2, "03_Atomic_Notes": 1})
        # newest-first by recency
        self.assertEqual(titles[0], "New Video")
        # each record carries its own folder so it can be opened cross-source
        new = next(r for r in out["records"] if r["title"] == "New Video")
        self.assertEqual(new["vault_path"], str(yt))
        self.assertEqual(new["path"], "new.md")
        self.assertEqual(new["source"], "youtube")

    def test_query_filters_across_sources(self):
        base, yt, atomic = _mkfolders()
        out = aggregate_value_notes([str(yt), str(atomic)], query="atomic")
        self.assertEqual([r["title"] for r in out["records"]], ["Atomic Idea"])

    def test_missing_folder_is_ignored(self):
        base, yt, atomic = _mkfolders()
        out = aggregate_value_notes([str(yt), str(base / "nope")])
        self.assertEqual(out["sources"], {"youtube": 2})

    def test_relevance_ranks_by_keyword_overlap(self):
        base = Path(tempfile.mkdtemp(prefix="vi-value-rel-"))
        yt = base / "youtube"; yt.mkdir()
        (yt / "a.md").write_text(
            "---\ntitle: CUDA agent runtime\ntags: [agent, gpu]\nsummary: deep dive\nclipped_at: \"2026-01-01\"\n---\n",
            encoding="utf-8")
        (yt / "b.md").write_text(
            "---\ntitle: Cooking pasta\ntags: [food]\nsummary: an agent helps you cook\nclipped_at: \"2026-06-01\"\n---\n",
            encoding="utf-8")
        out = aggregate_value_notes([str(yt)], query="agent", sort="relevance")
        titles = [r["title"] for r in out["records"]]
        # title+tags hit (a) outranks summary-only hit (b) despite b being newer
        self.assertEqual(titles, ["CUDA agent runtime", "Cooking pasta"])
        self.assertGreater(out["records"][0]["score"], out["records"][1]["score"])

    def test_relevance_excludes_non_overlapping(self):
        base, yt, atomic = _mkfolders()
        out = aggregate_value_notes([str(yt), str(atomic)], query="atomic", sort="relevance")
        self.assertEqual([r["title"] for r in out["records"]], ["Atomic Idea"])

    def test_relevance_empty_query_falls_back_to_recency(self):
        base, yt, atomic = _mkfolders()
        out = aggregate_value_notes([str(yt), str(atomic)], sort="relevance")
        self.assertEqual(out["records"][0]["title"], "New Video")
        self.assertNotIn("score", out["records"][0])


if __name__ == "__main__":
    unittest.main()
