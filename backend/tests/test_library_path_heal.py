"""Index note_path self-heal: stale prefixes must not duplicate library records."""
import json
import tempfile
import unittest
from pathlib import Path

from app_state import AppStateRuntime

NOTE = "---\ntype: source\ntitle: \"%s\"\ncategory: AI LLM\n---\n\n# %s\n"


class LibraryPathHealTests(unittest.TestCase):
    def setUp(self):
        # workspace = the youtube folder itself (what the library uses)
        self.root = Path(tempfile.mkdtemp(prefix="vi-heal-")) / "note_study/02_Sources/youtube"
        (self.root / "videos").mkdir(parents=True)
        (self.root / "videos/new_note.md").write_text(NOTE % ("新格式", "新格式"), encoding="utf-8")
        (self.root / "legacy_note.md").write_text(NOTE % ("舊格式", "舊格式"), encoding="utf-8")
        index = {
            "version": 1,
            "items": {
                # #6 vault-root era: path relative to the vault ROOT
                "vid_new": {"video_id": "vid_new", "title": "新格式",
                            "note_path": "02_Sources/youtube/videos/new_note.md", "category": "AI LLM"},
                # vaultwiki era: path relative to the old repo root
                "vid_old": {"video_id": "vid_old", "title": "舊格式",
                            "note_path": "note_study/02_Sources/youtube/legacy_note.md", "category": "AI LLM"},
            },
        }
        (self.root / "_youtube_index.json").write_text(json.dumps(index), encoding="utf-8")

    def test_stale_prefixes_resolve_and_do_not_duplicate(self):
        model = AppStateRuntime.local_library_read_model_for_workspace(
            self.root, index_path="_youtube_index.json", limit=50
        )
        records = model["read_model"]["records"] if "read_model" in model else model["records"]
        paths = sorted(r["path"] for r in records)
        self.assertEqual(paths, ["legacy_note.md", "videos/new_note.md"])
        self.assertEqual(model["record_count"] if "record_count" in model else model["read_model"]["record_count"], 2)
        for record in records:
            self.assertTrue((self.root / record["path"]).is_file())
            self.assertEqual(record["category"], "AI LLM")


if __name__ == "__main__":
    unittest.main()
