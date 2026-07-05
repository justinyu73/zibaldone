"""Write-preview guard tests for the Video Intake App state runtime.

The note write path is the product's most sensitive boundary. These tests pin
the invariant that a note preview is always created write-blocked
("writeback_requires_separate_approval") and only forms from accepted review
decisions — never from unreviewed or rejected evidence. All writes here hit a
throwaway temp SQLite workspace and never touch a real note file.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_state as A  # noqa: E402


class WritePreviewGuardTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="vi-wp-"))
        self.rt = A.AppStateRuntime.open(self.root, create=True)
        ws = self.rt.ensure_workspace()
        self.workspace_id = ws["workspace_id"]
        self.target = self.rt.create_storage_target(
            workspace_id=self.workspace_id,
            root_path=str(self.root / "vault"),
        )
        self.source = self.rt.create_source(
            workspace_id=self.workspace_id,
            platform="youtube",
            canonical_url="https://youtu.be/abc",
            canonical_id="abc",
            title="Preview Demo",
            evidence_segments=[
                {"lane": "native_caption", "text": "alpha", "timestamp_start": 0.0, "timestamp_end": 1.0},
            ],
        )
        self.source_id = self.source["source_id"]
        self.segment_id = self.rt.list_evidence(source_id=self.source_id)[0]["segment_id"]

    def test_empty_accepted_segments_raises(self):
        with self.assertRaises(A.AppStateError):
            self.rt.create_write_preview(
                source_id=self.source_id,
                target_id=self.target["target_id"],
                accepted_segment_ids=[],
            )

    def test_preview_from_unaccepted_segment_raises(self):
        # No review decision recorded yet → preview must refuse.
        with self.assertRaises(A.AppStateError):
            self.rt.create_write_preview(
                source_id=self.source_id,
                target_id=self.target["target_id"],
                accepted_segment_ids=[self.segment_id],
            )

    def test_rejected_segment_cannot_form_preview(self):
        self.rt.review_segment(segment_id=self.segment_id, decision="rejected")
        with self.assertRaises(A.AppStateError):
            self.rt.create_write_preview(
                source_id=self.source_id,
                target_id=self.target["target_id"],
                accepted_segment_ids=[self.segment_id],
            )

    def test_accepted_segment_preview_is_write_blocked_by_default(self):
        self.rt.review_segment(segment_id=self.segment_id, decision="accepted")
        preview = self.rt.create_write_preview(
            source_id=self.source_id,
            target_id=self.target["target_id"],
            accepted_segment_ids=[self.segment_id],
        )
        self.assertEqual(preview["write_allowed"], 0)
        self.assertEqual(preview["write_block_reason"], "writeback_requires_separate_approval")
        # No note file is produced by previewing.
        self.assertEqual(list((self.root / "vault").glob("**/*.md")) if (self.root / "vault").exists() else [], [])

    def test_invalid_review_decision_raises(self):
        with self.assertRaises(A.AppStateError):
            self.rt.review_segment(segment_id=self.segment_id, decision="approve_everything")

    def test_missing_source_raises(self):
        self.rt.review_segment(segment_id=self.segment_id, decision="accepted")
        with self.assertRaises(A.AppStateError):
            self.rt.create_write_preview(
                source_id="src-missing",
                target_id=self.target["target_id"],
                accepted_segment_ids=[self.segment_id],
            )


if __name__ == "__main__":
    unittest.main()
