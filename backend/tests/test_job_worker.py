"""In-process job worker tests (block #5, gated scope: stops at paid boundary).

Locks the core safety property JY approved: the worker auto-advances FREE
stages but never autonomously enters a paid (translate/summary) or durable
(write_note) stage — it blocks for explicit per-job approval. No provider call,
no spend; pure durable state transitions against a temp workspace.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_state as A  # noqa: E402
import job_worker as W  # noqa: E402

PAID_OR_DURABLE = {"translate", "summarize", "write_note"}


class JobWorkerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="vi-worker-"))
        self.rt = A.AppStateRuntime.open(self.root, create=True)
        ws = self.rt.ensure_workspace()
        self.rt.create_source(
            workspace_id=ws["workspace_id"],
            platform="youtube",
            canonical_url="https://youtu.be/abc",
            canonical_id="abc",
            title="Worker Demo",
        )
        self.job_id = self.rt.route_source(
            source_id=A.stable_id("src", "youtube", "abc"), route_state="native_caption_available"
        )["job_id"]
        self.worker = W.JobWorker(self.rt)

    def _job(self):
        return self.worker._job(self.job_id)

    def test_runs_free_stages_then_blocks_before_paid(self):
        steps = self.worker.run_until_blocked(self.job_id)
        last = steps[-1]
        self.assertFalse(last["advanced"])
        self.assertEqual(last["blocked_on"], "translate")
        self.assertEqual(last["boundary"], "paid")
        self.assertTrue(last["requires_approval"])
        self.assertEqual(self._job()["status"], W.BLOCKED_STATUS)

    def test_worker_never_autonomously_enters_paid_or_durable_stage(self):
        self.worker.run_until_blocked(self.job_id)
        self.assertNotIn(self._job()["stage"], PAID_OR_DURABLE)

    def test_approve_boundary_crosses_exactly_one_paid_step(self):
        self.worker.run_until_blocked(self.job_id)  # blocked before translate
        self.worker.approve_boundary(self.job_id)
        self.assertEqual(self._job()["stage"], "translate")
        # next free-run immediately blocks again before summarize (also paid)
        steps = self.worker.run_until_blocked(self.job_id)
        self.assertEqual(steps[-1]["blocked_on"], "summarize")

    def test_full_pipeline_completes_only_with_approvals(self):
        # translate -> summarize -> write_note each need an explicit approval
        for _ in range(5):
            self.worker.run_until_blocked(self.job_id)
            job = self._job()
            if job["status"] == W.BLOCKED_STATUS:
                self.worker.approve_boundary(self.job_id)
            if job["status"] == "completed":
                break
        # after approvals the pipeline reaches completed
        self.worker.run_until_blocked(self.job_id)
        self.assertEqual(self._job()["status"], "completed")

    def test_cancel_halts_advance(self):
        self.worker.cancel(self.job_id)
        self.assertEqual(self._job()["status"], W.CANCELLED_STATUS)
        decision = self.worker.advance(self.job_id)
        self.assertFalse(decision["advanced"])
        self.assertTrue(decision.get("halted"))

    def test_approve_when_not_blocked_raises(self):
        with self.assertRaises(A.AppStateError):
            self.worker.approve_boundary(self.job_id)


if __name__ == "__main__":
    unittest.main()
