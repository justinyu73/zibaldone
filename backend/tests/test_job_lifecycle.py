"""Job lifecycle + durability tests (block #5, in-band).

Jobs were created but never transitioned — no durable progress, retry, or
resume. These tests cover the new lifecycle methods against a temp SQLite
workspace and prove durability: progress persists across a fresh runtime
instance (the point of #5), and retries promote to failed_terminal once the
limit is exceeded (matching the retry>=3 escalation rule).
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_state as A  # noqa: E402


class JobLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="vi-job-"))
        self.rt = A.AppStateRuntime.open(self.root, create=True)
        ws = self.rt.ensure_workspace()
        self.rt.create_source(
            workspace_id=ws["workspace_id"],
            platform="youtube",
            canonical_url="https://youtu.be/abc",
            canonical_id="abc",
            title="Job Demo",
        )
        self.source_id = A.stable_id("src", "youtube", "abc")
        self.job = self.rt.route_source(source_id=self.source_id, route_state="native_caption_available")
        self.job_id = self.job["job_id"]

    def test_update_job_progress_persists(self):
        updated = self.rt.update_job_progress(job_id=self.job_id, status="running", progress=42)
        self.assertEqual(updated["status"], "running")
        self.assertEqual(updated["progress"], 42)

    def test_progress_is_durable_across_new_runtime_instance(self):
        self.rt.update_job_progress(job_id=self.job_id, status="running", progress=55)
        reopened = A.AppStateRuntime.open(self.root, create=False)
        with reopened.connect_read_only() as conn:
            row = conn.execute("SELECT status, progress FROM jobs WHERE job_id = ?", (self.job_id,)).fetchone()
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["progress"], 55)

    def test_invalid_progress_raises(self):
        with self.assertRaises(A.AppStateError):
            self.rt.update_job_progress(job_id=self.job_id, status="running", progress=150)

    def test_update_missing_job_raises(self):
        with self.assertRaises(A.AppStateError):
            self.rt.update_job_progress(job_id="job-missing", status="running", progress=1)

    def test_retry_increments_then_goes_terminal_past_limit(self):
        for expected in range(1, A.MAX_JOB_RETRIES + 1):
            job = self.rt.record_job_retry(job_id=self.job_id)
            self.assertEqual(job["retry_count"], expected)
            self.assertEqual(job["status"], "failed_recoverable")
        # one past the limit -> terminal
        terminal = self.rt.record_job_retry(job_id=self.job_id)
        self.assertEqual(terminal["retry_count"], A.MAX_JOB_RETRIES + 1)
        self.assertEqual(terminal["status"], "failed_terminal")

    def test_lifecycle_read_model_buckets_and_exhausted(self):
        # drive the single job to terminal
        for _ in range(A.MAX_JOB_RETRIES + 1):
            self.rt.record_job_retry(job_id=self.job_id)
        model = self.rt.job_lifecycle_read_model()
        self.assertTrue(model["read_only"])
        self.assertEqual(model["retry_limit"], A.MAX_JOB_RETRIES)
        self.assertEqual(model["counts"]["terminal"], 1)
        self.assertEqual(model["retry_exhausted"], [self.job_id])


class ResumeRecommendationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="vi-resume-"))
        self.rt = A.AppStateRuntime.open(self.root, create=True)
        self.ws = self.rt.ensure_workspace()

    def _route_job(self):
        self.rt.create_source(
            workspace_id=self.ws["workspace_id"],
            platform="youtube",
            canonical_url="https://youtu.be/abc",
            canonical_id="abc",
            title="Resume Demo",
        )
        sid = A.stable_id("src", "youtube", "abc")
        return self.rt.route_source(source_id=sid, route_state="native_caption_available")["job_id"]

    def _recommendation(self):
        return self.rt.resume_read_model()["resume_snapshot"]["resume_recommendation"]

    def test_no_job_recommends_none(self):
        rec = self._recommendation()
        self.assertFalse(rec["resumable"])
        self.assertEqual(rec["action"], "none")

    def test_preview_ready_recommends_open_preview(self):
        self._route_job()
        rec = self._recommendation()
        self.assertTrue(rec["resumable"])
        self.assertEqual(rec["action"], "open_preview")

    def test_needs_review_recommends_continue_review(self):
        job_id = self._route_job()
        self.rt.update_job_progress(job_id=job_id, status="needs_review", progress=60)
        self.assertEqual(self._recommendation()["action"], "continue_review")

    def test_recoverable_failure_recommends_retry_with_remaining(self):
        job_id = self._route_job()
        self.rt.record_job_retry(job_id=job_id)
        rec = self._recommendation()
        self.assertEqual(rec["action"], "retry")
        self.assertTrue(rec["resumable"])
        self.assertEqual(rec["retries_remaining"], A.MAX_JOB_RETRIES - 1)

    def test_terminal_failure_blocks_resume(self):
        job_id = self._route_job()
        for _ in range(A.MAX_JOB_RETRIES + 1):
            self.rt.record_job_retry(job_id=job_id)
        rec = self._recommendation()
        self.assertEqual(rec["action"], "blocked_retry_exhausted")
        self.assertFalse(rec["resumable"])
        self.assertEqual(rec["retries_remaining"], 0)


if __name__ == "__main__":
    unittest.main()
