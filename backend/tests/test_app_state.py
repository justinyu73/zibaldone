"""Unit tests for the Video Intake App local state runtime.

Stdlib unittest only — no pytest, no network, no provider/media/credential
calls. Each runtime test runs against a throwaway temp workspace, so nothing
touches durable product state. These tests lock the product's pure-function
contracts and the read-only safety invariants (zero trust counters, all
write/provider/media/credential gates blocked) that the governance layer
depends on.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_state as A  # noqa: E402


class PureHelperTests(unittest.TestCase):
    def test_stable_id_is_deterministic_and_prefixed(self):
        a = A.stable_id("src", "youtube", "abc")
        b = A.stable_id("src", "youtube", "abc")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("src-"))
        self.assertNotEqual(a, A.stable_id("src", "youtube", "abd"))

    def test_sha256_text_prefix_and_stability(self):
        digest = A.sha256_text("hello")
        self.assertTrue(digest.startswith("sha256:"))
        self.assertEqual(digest, A.sha256_text("hello"))
        self.assertNotEqual(digest, A.sha256_text("world"))

    def test_db_path_for_workspace_appends_db_filename(self):
        path = A.db_path_for_workspace("/tmp/some-ws")
        self.assertEqual(path.name, A.DB_FILENAME)

    def test_infer_platform_from_url(self):
        self.assertEqual(A.infer_platform({"url": "https://youtu.be/x"}), "youtube")
        self.assertEqual(A.infer_platform({"canonical_url": "https://www.youtube.com/watch?v=x"}), "youtube")
        self.assertEqual(A.infer_platform({"url": "https://instagram.com/reel/x"}), "instagram")
        self.assertEqual(A.infer_platform({"url": "https://x.com/u/status/1"}), "x")
        self.assertEqual(A.infer_platform({"url": "https://example.com/v"}), "local")

    def test_normalize_source_type_platform_defaults(self):
        self.assertEqual(A.normalize_source_type("", "youtube"), "YT")
        self.assertEqual(A.normalize_source_type("shorts", "youtube"), "YT")
        self.assertEqual(A.normalize_source_type("reel", "instagram"), "Reels")
        self.assertEqual(A.normalize_source_type("thread", "threads"), "Threads")
        self.assertEqual(A.normalize_source_type("tweet", "x"), "X")
        # An explicit non-default value is preserved verbatim.
        self.assertEqual(A.normalize_source_type("Lecture", "youtube"), "Lecture")
        # Unknown platform with empty value falls back to upper-cased platform.
        self.assertEqual(A.normalize_source_type("", "vimeo"), "VIMEO")

    def test_normalize_keywords_handles_list_string_and_other(self):
        self.assertEqual(A.normalize_keywords(["a", " b ", ""]), ["a", "b"])
        self.assertEqual(A.normalize_keywords("a, b，c"), ["a", "b", "c"])
        self.assertEqual(A.normalize_keywords(123), [])
        self.assertEqual(A.normalize_keywords(None), [])

    def test_local_library_filter_match(self):
        record = {"category": "AI 產品", "source_type": "YT"}
        self.assertTrue(A.local_library_filter_match(record, category="ai", source_type="yt"))
        self.assertFalse(A.local_library_filter_match(record, category="finance", source_type=""))
        self.assertFalse(A.local_library_filter_match(record, category="", source_type="reels"))

    def test_local_library_query_match(self):
        record = {"title": "Founder Playbook", "keywords": ["startup", "moat"]}
        self.assertTrue(A.local_library_query_match(record, ""))
        self.assertTrue(A.local_library_query_match(record, "founder"))
        self.assertTrue(A.local_library_query_match(record, "MOAT"))
        self.assertFalse(A.local_library_query_match(record, "unrelated"))


class NormalizeRecordTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="vi-norm-"))

    def test_written_indexed_record_marks_rollback_available_but_not_executable(self):
        raw = {
            "video_id": "wSp6AiNIrsY",
            "canonical_url": "https://youtu.be/wSp6AiNIrsY",
            "title": "Sample",
            "path": "note_study/02_Sources/youtube/wSp6AiNIrsY_yt.md",
            "reviewed_evidence": {
                "note_path": "note_study/02_Sources/youtube/wSp6AiNIrsY_yt.md",
                "current_hash": "sha256:deadbeef",
                "accepted_segment_count": 3,
                "preview_id": "preview-1",
            },
        }
        rec = A.normalize_local_library_record(raw, root=self.root)
        self.assertEqual(rec["platform"], "youtube")
        self.assertEqual(rec["source_type"], "YT")
        self.assertEqual(rec["source_id"], "wSp6AiNIrsY")
        detail = rec["source_note_detail"]
        self.assertEqual(detail["note"]["index_status"], "indexed")
        self.assertEqual(detail["note"]["writeback_status"], "written_indexed")
        self.assertTrue(detail["rollback"]["available"])
        # Rollback is display-only: a normalized read-model never authorizes execution.
        self.assertFalse(detail["rollback"]["execution_allowed"])
        self.assertTrue(detail["rollback"]["display_only"])
        self.assertEqual(detail["trust_counters"], {
            "source_note_writes": 0,
            "index_writes": 0,
            "sqlite_mutations": 0,
            "provider_call_count": 0,
            "media_download_count": 0,
            "credential_reads": 0,
            "rollback_executions": 0,
        })

    def test_unwritten_record_is_not_indexed(self):
        raw = {"video_id": "abc", "canonical_url": "https://youtu.be/abc", "title": "No note"}
        rec = A.normalize_local_library_record(raw, root=self.root)
        detail = rec["source_note_detail"]
        self.assertEqual(detail["note"]["index_status"], "not_indexed")
        self.assertEqual(detail["note"]["writeback_status"], "not_written")
        self.assertFalse(detail["rollback"]["available"])


class RuntimeStateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="vi-rt-"))
        self.rt = A.AppStateRuntime.open(self.root, create=True)
        self.ws = self.rt.ensure_workspace()

    def test_health_ok_after_create(self):
        health = self.rt.health()
        self.assertTrue(health["ok"])
        self.assertTrue(health["database_exists"])
        self.assertEqual(health["schema_version"], str(A.SCHEMA_VERSION))
        self.assertGreaterEqual(health["table_count"], 11)

    def test_open_without_create_on_missing_root_raises(self):
        missing = self.root / "does-not-exist"
        with self.assertRaises(A.AppStateError):
            A.AppStateRuntime.open(missing, create=False)

    def test_create_source_with_evidence_counts_segments(self):
        source = self.rt.create_source(
            workspace_id=self.ws["workspace_id"],
            platform="youtube",
            canonical_url="https://youtu.be/abc",
            canonical_id="abc",
            title="Demo",
            evidence_segments=[
                {"lane": "native_caption", "text": "hello", "timestamp_start": 0.0, "timestamp_end": 1.0},
                {"lane": "native_caption", "text": "world", "timestamp_start": 1.0, "timestamp_end": 2.0},
            ],
        )
        self.assertEqual(source["evidence_count"], 2)
        self.assertEqual(source["route_state"], "source_ready")

    def test_route_source_native_caption_sets_preview_ready_job(self):
        self.rt.create_source(
            workspace_id=self.ws["workspace_id"],
            platform="youtube",
            canonical_url="https://youtu.be/abc",
            canonical_id="abc",
        )
        source_id = A.stable_id("src", "youtube", "abc")
        job = self.rt.route_source(source_id=source_id, route_state="native_caption_available")
        self.assertEqual(job["status"], "preview_ready")
        self.assertEqual(job["progress"], 100)

    def test_metrics_table_counts_and_zero_trust_counters(self):
        self.rt.create_source(
            workspace_id=self.ws["workspace_id"],
            platform="youtube",
            canonical_url="https://youtu.be/abc",
            canonical_id="abc",
        )
        metrics = self.rt.metrics()
        self.assertEqual(metrics["table_counts"]["sources"], 1)
        self.assertEqual(metrics["table_counts"]["workspaces"], 1)
        for counter in (
            "provider_call_count",
            "media_download_count",
            "credential_reads",
            "source_note_writes",
            "index_writes",
            "queue_mutations",
        ):
            self.assertEqual(metrics[counter], 0, f"{counter} must stay zero")
        self.assertFalse(metrics["scheduler_installed"])

    def test_control_plane_read_model_is_read_only_with_blocked_gates(self):
        cp = self.rt.control_plane_read_model()
        self.assertTrue(cp["read_only"])
        self.assertEqual(cp["blocked_gates"], {
            "writeback_allowed": False,
            "provider_runtime_allowed": False,
            "media_runtime_allowed": False,
            "scheduler_installed": False,
            "credential_reads_allowed": False,
        })
        for value in cp["trust_counters"].values():
            self.assertEqual(value, 0)

    def test_source_detail_read_model_returns_source_identity(self):
        self.rt.create_source(
            workspace_id=self.ws["workspace_id"],
            platform="youtube",
            canonical_url="https://youtu.be/abc",
            canonical_id="abc",
            title="Detail Demo",
        )
        source_id = A.stable_id("src", "youtube", "abc")
        detail = self.rt.source_detail_read_model(source_id=source_id)
        self.assertEqual(detail["source"]["source_id"], source_id)
        self.assertEqual(detail["source"]["title"], "Detail Demo")

    def test_source_detail_read_model_missing_source_raises(self):
        with self.assertRaises(A.AppStateError):
            self.rt.source_detail_read_model(source_id="src-missing")


if __name__ == "__main__":
    unittest.main()
