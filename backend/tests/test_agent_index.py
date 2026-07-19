"""Agent Bridge: local metadata projection, no model/network/writeback."""
import json
import tempfile
import unittest
from pathlib import Path

from agent_index import (
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

    def test_write_creates_owned_index_and_manifest_then_is_idempotent(self):
        result = generate_agent_index(str(self.root), write=True, confirm=True)
        self.assertTrue(result["generated"])
        index = (self.root / AGENT_INDEX_PATH).read_text(encoding="utf-8")
        manifest = json.loads((self.root / AGENT_MANIFEST_PATH).read_text(encoding="utf-8"))
        self.assertIn("# Zibaldone Agent Index", index)
        self.assertIn("Agent Bridge", index)
        self.assertIn("../../02_Sources/youtube/video.md", index)
        self.assertEqual(manifest["generated_by"], "zibaldone")
        self.assertEqual(manifest["note_count"], 2)
        self.assertEqual(agent_index_status(str(self.root))["managed"], True)

        second = generate_agent_index(str(self.root), write=True, confirm=True)
        self.assertFalse(second["generated"])
        self.assertFalse(second["changed"])

    def test_write_requires_confirmation_and_does_not_overwrite_foreign_index(self):
        with self.assertRaises(AgentIndexError):
            generate_agent_index(str(self.root), write=True)
        target = self.root / AGENT_INDEX_PATH
        target.parent.mkdir(parents=True)
        target.write_text("# user-owned\n", encoding="utf-8")
        with self.assertRaises(AgentIndexError):
            generate_agent_index(str(self.root), write=True, confirm=True)
        self.assertEqual(target.read_text(encoding="utf-8"), "# user-owned\n")


if __name__ == "__main__":
    unittest.main()
