"""In-process job worker for the source-to-note pipeline (block #5, gated scope).

Scope approved by JY: an app-managed in-process worker (no OS scheduler, dies
with the app) that auto-advances jobs through FREE stages and STOPS at the
paid (translate/summary) or durable-write boundary, marking the job
`blocked_awaiting_approval`. The worker itself NEVER calls a provider or writes
a note — it only advances durable job state, so it spends nothing autonomously.
Crossing a paid/durable boundary is an explicit per-job approval
(`approve_boundary`), not worker autonomy.
"""
from __future__ import annotations

from typing import Any

STAGE_PIPELINE = ["queued", "caption_fetch", "translate", "summarize", "write_note", "completed"]
STAGE_BOUNDARY = {
    "queued": "free",
    "caption_fetch": "free",
    "translate": "paid",
    "summarize": "paid",
    "write_note": "durable",
    "completed": "done",
}
BLOCKED_STATUS = "blocked_awaiting_approval"
CANCELLED_STATUS = "cancelled"
GATED_BOUNDARIES = {"paid", "durable"}
_HALTED_STATUSES = {BLOCKED_STATUS, CANCELLED_STATUS, "completed", "failed_terminal"}


def next_stage(stage: str) -> str | None:
    idx = STAGE_PIPELINE.index(stage) if stage in STAGE_PIPELINE else 0
    return STAGE_PIPELINE[idx + 1] if idx + 1 < len(STAGE_PIPELINE) else None


def stage_boundary(stage: str) -> str:
    return STAGE_BOUNDARY.get(stage, "free")


def _progress_for(stage: str) -> int:
    return round(STAGE_PIPELINE.index(stage) / (len(STAGE_PIPELINE) - 1) * 100)


class JobWorker:
    def __init__(self, runtime: Any):
        self.runtime = runtime

    def _job(self, job_id: str) -> dict[str, Any]:
        with self.runtime.connect_read_only() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            from app_state import AppStateError

            raise AppStateError(f"job does not exist: {job_id}")
        return dict(row)

    def advance(self, job_id: str) -> dict[str, Any]:
        """Advance one free step; stop (block) before a paid/durable boundary."""
        job = self._job(job_id)
        if job["status"] in _HALTED_STATUSES:
            return {"advanced": False, "halted": True, "status": job["status"]}
        nxt = next_stage(str(job["stage"]))
        if nxt is None:
            return {"advanced": False, "reason": "no_next_stage"}
        boundary = stage_boundary(nxt)
        if boundary in GATED_BOUNDARIES:
            self.runtime.set_job_stage(
                job_id=job_id, stage=str(job["stage"]), status=BLOCKED_STATUS, progress=int(job["progress"])
            )
            return {"advanced": False, "blocked_on": nxt, "boundary": boundary, "requires_approval": True}
        status = "completed" if nxt == "completed" else "running"
        self.runtime.set_job_stage(job_id=job_id, stage=nxt, status=status, progress=_progress_for(nxt))
        return {"advanced": True, "stage": nxt, "boundary": boundary}

    def run_until_blocked(self, job_id: str, max_steps: int = 20) -> list[dict[str, Any]]:
        steps = []
        for _ in range(max_steps):
            decision = self.advance(job_id)
            steps.append(decision)
            if not decision.get("advanced"):
                break
        return steps

    def approve_boundary(self, job_id: str) -> dict[str, Any]:
        """Explicit per-job approval: cross exactly one blocked paid/durable boundary."""
        job = self._job(job_id)
        if job["status"] != BLOCKED_STATUS:
            from app_state import AppStateError

            raise AppStateError("job is not awaiting approval")
        nxt = next_stage(str(job["stage"]))
        status = "completed" if nxt == "completed" else "running"
        return self.runtime.set_job_stage(
            job_id=job_id, stage=nxt, status=status, progress=_progress_for(nxt)
        )

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self._job(job_id)
        return self.runtime.set_job_stage(
            job_id=job_id, stage=str(job["stage"]), status=CANCELLED_STATUS, progress=int(job["progress"])
        )
