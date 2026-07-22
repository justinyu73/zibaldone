"""Agent Bridge: local metadata projection, no model/network/writeback."""
import tempfile
import unittest
from pathlib import Path

from agent_index import (
    AGENT_CONCEPT_DIR,
    AGENT_INDEX_PATH,
    AGENT_MANIFEST_PATH,
    AgentIndexError,
    agent_index_status,
    generate_agent_index,
    scan_vault,
)


class AgentIndexTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zibaldone-agent-index-"))
        (self.root / "01_Inbox").mkdir()
        (self.root / "02_Sources/youtube").mkdir(parents=True)
        (self.root / "_attachments").mkdir()
        (self.root / "_trash").mkdir()
        (self.root / "_attachments/hidden.md").write_text("# should not appear\n", encoding="utf-8")
        (self.root / "_trash/old.md").write_text("# should not appear\n", encoding="utf-8")
        (self.root / "01_Inbox/quick.md").write_text(
            "---\ntype: source\ntitle: \"待消化\"\nstatus: inbox\ntags: [capture, manual]\nupdated: 2026-07-19\n---\n\n# 待消化\n\n參考 [[02_Sources/youtube/video.md]].\n",
            encoding="utf-8",
        )
        self.source = self.root / "02_Sources/youtube/video.md"
        self.source.write_text(
            "---\ntype: source\ntitle: \"Agent Bridge\"\nsource: youtube\nurl: https://example.invalid/video\nsummary: 可追溯摘要\n---\n\n# Agent Bridge\n",
            encoding="utf-8",
        )

    def test_dry_run_is_read_only_and_has_stable_metadata_projection(self):
        before = self.source.read_bytes()
        result = generate_agent_index(str(self.root))

        self.assertTrue(result["dry_run"])
        self.assertFalse(result["generated"])
        self.assertEqual(result["note_count"], 2)
        self.assertFalse((self.root / AGENT_INDEX_PATH).exists())
        self.assertEqual(self.source.read_bytes(), before)

        preview = scan_vault(str(self.root))
        self.assertEqual([item["path"] for item in preview["records"]], ["01_Inbox/quick.md", "02_Sources/youtube/video.md"])
        self.assertEqual(preview["records"][0]["links"], ["[[02_Sources/youtube/video.md]]"])

    def test_write_creates_okf_bundle_then_is_idempotent(self):
        result = generate_agent_index(str(self.root), write=True, confirm=True)
        self.assertTrue(result["generated"])
        index = (self.root / AGENT_INDEX_PATH).read_text(encoding="utf-8")
        concept = (self.root / AGENT_CONCEPT_DIR / "02_Sources/youtube/video.md").read_text(encoding="utf-8")
        self.assertIn('okf_version: "0.1"', index)
        self.assertIn("# Zibaldone Agent Bundle", index)
        self.assertIn("Agent Bridge", index)
        self.assertIn("concepts/02_Sources/youtube/video.md", index)
        self.assertIn('type: "source"', concept)
        self.assertIn('zibaldone_source_path: "02_Sources/youtube/video.md"', concept)
        self.assertIn("Original note: [02_Sources/youtube/video.md]", concept)
        self.assertFalse((self.root / AGENT_MANIFEST_PATH).exists())
        self.assertEqual(agent_index_status(str(self.root))["managed"], True)
        self.assertEqual(agent_index_status(str(self.root))["okf_version"], "0.1")

        second = generate_agent_index(str(self.root), write=True, confirm=True)
        self.assertFalse(second["generated"])
        self.assertFalse(second["changed"])

    def test_missing_type_uses_projection_only_note_fallback(self):
        note = self.root / "note-without-type.md"
        note.write_text("# Untyped note\n", encoding="utf-8")

        generate_agent_index(str(self.root), write=True, confirm=True)

        concept = self.root / AGENT_CONCEPT_DIR / "note-without-type.md"
        self.assertIn('type: "note"', concept.read_text(encoding="utf-8"))
        self.assertNotIn("---\ntype:", note.read_text(encoding="utf-8"))

    def test_write_requires_confirmation_and_does_not_overwrite_foreign_index(self):
        with self.assertRaises(AgentIndexError):
            generate_agent_index(str(self.root), write=True)
        target = self.root / AGENT_INDEX_PATH
        target.parent.mkdir(parents=True)
        target.write_text("# user-owned\n", encoding="utf-8")
        with self.assertRaises(AgentIndexError):
            generate_agent_index(str(self.root), write=True, confirm=True)
        self.assertEqual(target.read_text(encoding="utf-8"), "# user-owned\n")

    def test_write_does_not_overwrite_foreign_concept(self):
        generate_agent_index(str(self.root), write=True, confirm=True)
        target = self.root / AGENT_CONCEPT_DIR / "02_Sources/youtube/video.md"
        target.write_text("# user-owned concept\n", encoding="utf-8")

        with self.assertRaises(AgentIndexError):
            generate_agent_index(str(self.root), write=True, confirm=True)
        self.assertEqual(target.read_text(encoding="utf-8"), "# user-owned concept\n")


if __name__ == "__main__":
    unittest.main()
