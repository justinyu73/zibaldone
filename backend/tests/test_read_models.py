"""Read-only read-model tests for the Video Intake App state runtime.

These cover the library/index projection, evidence-review decision state,
retained-artifact view, and resume snapshot. All run against throwaway temp
workspaces and assert the shared safety contract: every read model is
read-only, never authorizes scan/write/sync, and keeps trust counters at zero.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_state as A  # noqa: E402


def _all_zero(counters):
    return all(value == 0 for value in counters.values())


class LocalLibraryReadModelTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="vi-lib-"))
        index = {
            "videos": {
                "vid1": {
                    "video_id": "vid1",
                    "canonical_url": "https://youtu.be/vid1",
                    "title": "Founder Playbook",
                    "category": "AI 產品",
                    "keywords": ["startup", "moat"],
                    "path": "notes/vid1.md",
                },
                "vid2": {
                    "video_id": "vid2",
                    "canonical_url": "https://instagram.com/reel/vid2",
                    "title": "Reels Clip",
                    "category": "行銷",
                    "keywords": ["ads"],
                },
            }
        }
        self.index_rel = "_index.json"
        (self.root / self.index_rel).write_text(json.dumps(index), encoding="utf-8")

    def _read(self, **kwargs):
        return A.AppStateRuntime.local_library_read_model_for_workspace(
            self.root, index_path=self.index_rel, **kwargs
        )

    def test_projects_records_read_only_with_intentional_local_scan(self):
        # Local-first product now scans the user's own folder (index + .md fallback),
        # but stays read-only: no note/index writes, no external sync. Fixture has no
        # stray .md, so record_count stays at the 2 indexed records.
        result = self._read()
        self.assertTrue(result["ok"])
        self.assertTrue(result["read_only"])
        rm = result["read_model"]
        self.assertEqual(rm["record_count"], 2)
        self.assertTrue(rm["filesystem_scan_allowed"])
        self.assertFalse(rm["external_api_sync_allowed"])
        self.assertEqual(rm["source_note_writes"], 0)
        self.assertEqual(rm["index_writes"], 0)
        self.assertTrue(_all_zero(result["trust_counters"]))

    def test_query_filters_matched_count(self):
        result = self._read(query="founder")
        self.assertEqual(result["read_model"]["record_count"], 2)
        self.assertEqual(result["read_model"]["matched_count"], 1)

    def test_source_type_filter_narrows_records(self):
        result = self._read(source_type="Reels")
        self.assertEqual(result["read_model"]["record_count"], 1)

    def test_missing_index_yields_empty_records(self):
        result = A.AppStateRuntime.local_library_read_model_for_workspace(
            self.root, index_path="absent.json"
        )
        self.assertEqual(result["read_model"]["record_count"], 0)
        self.assertFalse(result["search_summary"]["index_exists"])

    def test_path_traversal_index_path_rejected(self):
        with self.assertRaises(A.AppStateError):
            A.AppStateRuntime.local_library_read_model_for_workspace(
                self.root, index_path="../escape.json"
            )

    def test_absolute_index_path_rejected(self):
        with self.assertRaises(A.AppStateError):
            A.AppStateRuntime.local_library_read_model_for_workspace(
                self.root, index_path="/etc/passwd"
            )


class EvidenceReviewStateTests(unittest.TestCase):
    def test_missing_db_returns_missing_state_not_ok(self):
        root = Path(tempfile.mkdtemp(prefix="vi-rev-"))
        rt = A.AppStateRuntime(root)
        payload = rt.evidence_review_decision_state_read_model(source_id="src-x")
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["review_readiness"]["state"], "missing_db")
        self.assertFalse(payload["review_readiness"]["writeback_ready"])

    def test_source_not_found_returns_not_ok(self):
        root = Path(tempfile.mkdtemp(prefix="vi-rev-"))
        rt = A.AppStateRuntime.open(root, create=True)
        rt.ensure_workspace()
        payload = rt.evidence_review_decision_state_read_model(source_id="src-missing")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["review_readiness"]["state"], "source_not_found")

    def test_empty_source_id_raises(self):
        root = Path(tempfile.mkdtemp(prefix="vi-rev-"))
        rt = A.AppStateRuntime.open(root, create=True)
        with self.assertRaises(A.AppStateError):
            rt.evidence_review_decision_state_read_model(source_id="")


class RetainedArtifactReadModelTests(unittest.TestCase):
    def test_empty_workspace_has_no_artifacts_and_blocked_guards(self):
        root = Path(tempfile.mkdtemp(prefix="vi-art-"))
        rt = A.AppStateRuntime.open(root, create=True)
        rt.ensure_workspace()
        result = rt.retained_artifact_read_model()
        self.assertTrue(result["read_only"])
        self.assertEqual(result["retained_artifact_count"], 0)
        guard = result["production_exclusion_guard"]
        self.assertFalse(any(guard.values()), "every production-exclusion guard must stay False")
        self.assertTrue(_all_zero(result["trust_counters"]))


class ResumeReadModelTests(unittest.TestCase):
    def test_missing_db_returns_empty_state(self):
        root = Path(tempfile.mkdtemp(prefix="vi-res-"))
        payload = A.AppStateRuntime.resume_read_model_for_workspace(root)
        self.assertTrue(payload["empty_state"])
        self.assertEqual(payload["empty_reason"], "workspace_database_missing")
        self.assertTrue(payload["read_only"])

    def test_created_workspace_without_jobs_is_empty_but_ok(self):
        root = Path(tempfile.mkdtemp(prefix="vi-res-"))
        rt = A.AppStateRuntime.open(root, create=True)
        rt.ensure_workspace()
        payload = rt.resume_read_model(mode="last_active")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["read_only"])

    def test_unsupported_mode_raises(self):
        root = Path(tempfile.mkdtemp(prefix="vi-res-"))
        rt = A.AppStateRuntime.open(root, create=True)
        rt.ensure_workspace()
        with self.assertRaises(A.AppStateError):
            rt.resume_read_model(mode="time_travel")


if __name__ == "__main__":
    unittest.main()
