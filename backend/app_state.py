"""Local SQLite state runtime for the Video Intake App shell.

This module owns app workspace state only. It does not call providers, download
media, write source notes/indexes, read credentials, mutate external queues, or
install background runners.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


SCHEMA_VERSION = 1
DB_FILENAME = "video_intake_app.sqlite"
MAX_JOB_RETRIES = 3
TERMINAL_JOB_STATUSES = {"completed", "failed_terminal"}


class AppStateError(ValueError):
    """Raised when local app state input is invalid or inconsistent."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_id(prefix: str, *parts: object) -> str:
    raw = ":".join(str(part) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file_text(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8")) if path.exists() else "sha256:new-file"


def db_path_for_workspace(root_path: str | Path) -> Path:
    root = Path(root_path).expanduser().resolve()
    return root / DB_FILENAME


@dataclass(frozen=True)
class AppStateRuntime:
    """Small SQLite service for app-local state."""

    workspace_root: Path

    @classmethod
    def open(cls, workspace_root: str | Path, *, create: bool = False) -> "AppStateRuntime":
        root = Path(workspace_root).expanduser().resolve()
        if create:
            root.mkdir(parents=True, exist_ok=True)
        if not root.exists():
            raise AppStateError(f"workspace root does not exist: {root}")
        runtime = cls(root)
        if create:
            runtime.migrate()
        return runtime

    @property
    def db_path(self) -> Path:
        return db_path_for_workspace(self.workspace_root)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def connect_read_only(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise AppStateError(f"workspace database does not exist: {self.db_path}")
        uri = f"file:{quote(self.db_path.as_posix())}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA query_only = ON")
        return conn

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    root_path TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    privacy_policy TEXT NOT NULL,
                    retention_policy TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS storage_targets (
                    target_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
                    adapter_type TEXT NOT NULL,
                    root_path TEXT NOT NULL,
                    permissions TEXT NOT NULL,
                    write_mode TEXT NOT NULL,
                    UNIQUE(workspace_id, adapter_type, root_path)
                );

                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
                    platform TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    canonical_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    route_state TEXT NOT NULL,
                    permission_state TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(source_id),
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    provider_call_count INTEGER NOT NULL DEFAULT 0,
                    media_download_count INTEGER NOT NULL DEFAULT 0,
                    credential_reads INTEGER NOT NULL DEFAULT 0,
                    input_state_hash TEXT NOT NULL,
                    output_state_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evidence_segments (
                    segment_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(source_id),
                    lane TEXT NOT NULL,
                    timestamp_start REAL NOT NULL,
                    timestamp_end REAL NOT NULL,
                    text TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    warnings_json TEXT NOT NULL,
                    source_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS review_decisions (
                    decision_id TEXT PRIMARY KEY,
                    segment_id TEXT NOT NULL REFERENCES evidence_segments(segment_id),
                    decision TEXT NOT NULL,
                    reviewer_note TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS translations (
                    translation_id TEXT PRIMARY KEY,
                    segment_id TEXT NOT NULL REFERENCES evidence_segments(segment_id),
                    language TEXT NOT NULL,
                    model_policy TEXT NOT NULL,
                    text TEXT NOT NULL,
                    output_hash TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS summaries (
                    summary_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(source_id),
                    mode TEXT NOT NULL,
                    evidence_version TEXT NOT NULL,
                    output_hash TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS note_previews (
                    preview_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(source_id),
                    target_id TEXT NOT NULL REFERENCES storage_targets(target_id),
                    template_id TEXT NOT NULL,
                    output_hash TEXT NOT NULL,
                    write_allowed INTEGER NOT NULL DEFAULT 0,
                    write_block_reason TEXT NOT NULL,
                    accepted_segment_ids_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notes (
                    note_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(source_id),
                    target_id TEXT NOT NULL REFERENCES storage_targets(target_id),
                    path TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    current_hash TEXT NOT NULL,
                    write_status TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rollbacks (
                    rollback_id TEXT PRIMARY KEY,
                    note_id TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    rollback_action TEXT NOT NULL,
                    action_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS metrics (
                    metric_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    value TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    def health(self) -> dict[str, Any]:
        exists = self.db_path.exists()
        table_count = 0
        schema_version = ""
        if exists:
            with self.connect() as conn:
                table_count = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                    ).fetchone()[0]
                )
                row = conn.execute(
                    "SELECT value FROM schema_meta WHERE key='schema_version'"
                ).fetchone()
                schema_version = row["value"] if row else ""
        return {
            "ok": exists and schema_version == str(SCHEMA_VERSION),
            "workspace_root": str(self.workspace_root),
            "db_path": str(self.db_path),
            "database_exists": exists,
            "schema_version": schema_version,
            "table_count": table_count,
            "provider_call_count": 0,
            "media_download_count": 0,
            "credential_reads": 0,
            "source_note_writes": 0,
            "index_writes": 0,
            "queue_mutations": 0,
            "scheduler_installed": False,
        }

    def ensure_workspace(
        self,
        *,
        privacy_policy: str = "local_first_no_hidden_cloud_sync",
        retention_policy: str = "raw_media_temporary_by_default",
    ) -> dict[str, Any]:
        self.migrate()
        workspace_id = stable_id("ws", self.workspace_root)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO workspaces(
                    workspace_id, root_path, created_at, privacy_policy, retention_policy
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (workspace_id, str(self.workspace_root), utc_now(), privacy_policy, retention_policy),
            )
            return self._get_one(conn, "SELECT * FROM workspaces WHERE workspace_id = ?", workspace_id)

    def create_storage_target(
        self,
        *,
        workspace_id: str,
        root_path: str,
        adapter_type: str = "markdown_obsidian",
        permissions: str = "preview_required",
        write_mode: str = "preview_only",
    ) -> dict[str, Any]:
        target_root = str(Path(root_path).expanduser())
        target_id = stable_id("target", workspace_id, adapter_type, target_root)
        with self.connect() as conn:
            self._require_workspace(conn, workspace_id)
            conn.execute(
                """
                INSERT OR IGNORE INTO storage_targets(
                    target_id, workspace_id, adapter_type, root_path, permissions, write_mode
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (target_id, workspace_id, adapter_type, target_root, permissions, write_mode),
            )
            return self._get_one(conn, "SELECT * FROM storage_targets WHERE target_id = ?", target_id)

    def create_source(
        self,
        *,
        workspace_id: str,
        platform: str,
        canonical_url: str,
        canonical_id: str,
        title: str = "",
        route_state: str = "source_ready",
        permission_state: str = "public_metadata_and_caption_only",
        evidence_segments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        idempotency_key = f"source:{platform}:{canonical_id}"
        source_id = stable_id("src", platform, canonical_id)
        with self.connect() as conn:
            self._require_workspace(conn, workspace_id)
            conn.execute(
                """
                INSERT OR IGNORE INTO sources(
                    source_id, workspace_id, platform, canonical_url, canonical_id, title,
                    route_state, permission_state, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    workspace_id,
                    platform,
                    canonical_url,
                    canonical_id,
                    title,
                    route_state,
                    permission_state,
                    idempotency_key,
                    utc_now(),
                ),
            )
            for index, segment in enumerate(evidence_segments or [], start=1):
                self._insert_evidence_segment(conn, source_id, segment, index)
            source = self._get_one(conn, "SELECT * FROM sources WHERE source_id = ?", source_id)
            source["evidence_count"] = int(
                conn.execute(
                    "SELECT COUNT(*) FROM evidence_segments WHERE source_id = ?",
                    (source_id,),
                ).fetchone()[0]
            )
            return source

    def route_source(
        self,
        *,
        source_id: str,
        route_state: str,
        stage: str = "route_decision",
    ) -> dict[str, Any]:
        idempotency_key = f"route:{source_id}:{route_state}:v1"
        job_id = stable_id("job", idempotency_key)
        with self.connect() as conn:
            source = self._require_source(conn, source_id)
            input_hash = sha256_text(json.dumps(source, sort_keys=True, ensure_ascii=False))
            conn.execute(
                "UPDATE sources SET route_state = ? WHERE source_id = ?",
                (route_state, source_id),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO jobs(
                    job_id, source_id, stage, status, progress, idempotency_key,
                    retry_count, provider_call_count, media_download_count, credential_reads,
                    input_state_hash, output_state_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?, ?, ?)
                """,
                (
                    job_id,
                    source_id,
                    stage,
                    "preview_ready" if route_state == "native_caption_available" else "needs_review",
                    100,
                    idempotency_key,
                    input_hash,
                    sha256_text(route_state),
                    utc_now(),
                ),
            )
            return self._get_one(conn, "SELECT * FROM jobs WHERE job_id = ?", job_id)

    def _require_job(self, conn: sqlite3.Connection, job_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise AppStateError(f"job does not exist: {job_id}")
        return row_to_dict(row)

    def update_job_progress(self, *, job_id: str, status: str, progress: int) -> dict[str, Any]:
        """Durably persist a job's status and progress (resumable across restarts)."""
        if not 0 <= int(progress) <= 100:
            raise AppStateError("progress must be between 0 and 100")
        with self.connect() as conn:
            self._require_job(conn, job_id)
            conn.execute(
                "UPDATE jobs SET status = ?, progress = ? WHERE job_id = ?",
                (status, int(progress), job_id),
            )
            return self._get_one(conn, "SELECT * FROM jobs WHERE job_id = ?", job_id)

    def set_job_stage(self, *, job_id: str, stage: str, status: str, progress: int) -> dict[str, Any]:
        """Durably move a job to a pipeline stage (used by the in-process job worker)."""
        if not 0 <= int(progress) <= 100:
            raise AppStateError("progress must be between 0 and 100")
        with self.connect() as conn:
            self._require_job(conn, job_id)
            conn.execute(
                "UPDATE jobs SET stage = ?, status = ?, progress = ? WHERE job_id = ?",
                (stage, status, int(progress), job_id),
            )
            return self._get_one(conn, "SELECT * FROM jobs WHERE job_id = ?", job_id)

    def record_job_retry(self, *, job_id: str) -> dict[str, Any]:
        """Increment retry count; mark failed_terminal once the retry limit is exceeded."""
        with self.connect() as conn:
            job = self._require_job(conn, job_id)
            next_retry = int(job["retry_count"]) + 1
            terminal = next_retry > MAX_JOB_RETRIES
            conn.execute(
                "UPDATE jobs SET retry_count = ?, status = ? WHERE job_id = ?",
                (next_retry, "failed_terminal" if terminal else "failed_recoverable", job_id),
            )
            return self._get_one(conn, "SELECT * FROM jobs WHERE job_id = ?", job_id)

    def job_lifecycle_read_model(self) -> dict[str, Any]:
        """Read-only durable job view: lifecycle buckets + retry-exhausted jobs."""
        buckets: dict[str, list[dict[str, Any]]] = {
            "in_flight": [],
            "needs_review": [],
            "completed": [],
            "retryable": [],
            "terminal": [],
        }
        with self.connect_read_only() as conn:
            rows = conn.execute(
                """
                SELECT j.job_id, j.source_id, s.title, j.stage, j.status, j.progress,
                       j.retry_count, j.created_at
                FROM jobs j JOIN sources s ON s.source_id = j.source_id
                ORDER BY j.created_at DESC, j.job_id DESC
                """
            ).fetchall()
        for row in rows:
            job = row_to_dict(row)
            status = str(job["status"])
            if status == "failed_terminal":
                buckets["terminal"].append(job)
            elif status == "failed_recoverable":
                buckets["retryable"].append(job)
            elif status in ("preview_ready", "completed"):
                buckets["completed"].append(job)
            elif status == "needs_review":
                buckets["needs_review"].append(job)
            else:
                buckets["in_flight"].append(job)
        return {
            "ok": True,
            "read_only": True,
            "retry_limit": MAX_JOB_RETRIES,
            "counts": {name: len(items) for name, items in buckets.items()},
            "buckets": buckets,
            "retry_exhausted": [j["job_id"] for j in buckets["terminal"]],
        }

    def list_evidence(self, *, source_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_segments WHERE source_id = ? ORDER BY timestamp_start, segment_id",
                (source_id,),
            ).fetchall()
            return [row_to_dict(row) for row in rows]

    def review_segment(
        self,
        *,
        segment_id: str,
        decision: str,
        reviewer_note: str = "",
    ) -> dict[str, Any]:
        if decision not in {"accepted", "rejected", "pending_review"}:
            raise AppStateError(f"invalid review decision: {decision}")
        idempotency_key = f"review:{segment_id}:{decision}:v1"
        decision_id = stable_id("decision", idempotency_key)
        with self.connect() as conn:
            self._require_segment(conn, segment_id)
            conn.execute(
                """
                INSERT OR IGNORE INTO review_decisions(
                    decision_id, segment_id, decision, reviewer_note, decided_at, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (decision_id, segment_id, decision, reviewer_note, utc_now(), idempotency_key),
            )
            return self._get_one(conn, "SELECT * FROM review_decisions WHERE decision_id = ?", decision_id)

    def create_write_preview(
        self,
        *,
        source_id: str,
        target_id: str,
        accepted_segment_ids: list[str],
        template_id: str = "personal_learning_note_v1",
    ) -> dict[str, Any]:
        if not accepted_segment_ids:
            raise AppStateError("accepted_segment_ids is required for note preview")
        idempotency_key = f"preview:{source_id}:{target_id}:{sha256_text('|'.join(sorted(accepted_segment_ids)))}"
        preview_id = stable_id("preview", idempotency_key)
        with self.connect() as conn:
            self._require_source(conn, source_id)
            self._require_target(conn, target_id)
            for segment_id in accepted_segment_ids:
                self._require_accepted_decision(conn, segment_id)
            output_hash = sha256_text(json.dumps(accepted_segment_ids, sort_keys=True))
            conn.execute(
                """
                INSERT OR IGNORE INTO note_previews(
                    preview_id, source_id, target_id, template_id, output_hash, write_allowed,
                    write_block_reason, accepted_segment_ids_json, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    preview_id,
                    source_id,
                    target_id,
                    template_id,
                    output_hash,
                    "writeback_requires_separate_approval",
                    json.dumps(accepted_segment_ids, ensure_ascii=False),
                    idempotency_key,
                    utc_now(),
                ),
            )
            return self._get_one(conn, "SELECT * FROM note_previews WHERE preview_id = ?", preview_id)

    def metrics(self) -> dict[str, Any]:
        with self.connect() as conn:
            table_counts = {}
            for table in [
                "workspaces",
                "storage_targets",
                "sources",
                "jobs",
                "evidence_segments",
                "review_decisions",
                "note_previews",
                "rollbacks",
            ]:
                table_counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            return {
                "table_counts": table_counts,
                "provider_call_count": 0,
                "media_download_count": 0,
                "credential_reads": 0,
                "source_note_writes": 0,
                "index_writes": 0,
                "queue_mutations": 0,
                "scheduler_installed": False,
            }

    def control_plane_read_model(self) -> dict[str, Any]:
        """Return read-only dashboard state for the app control plane."""
        health = self.health()
        with self.connect() as conn:
            today = utc_now()[:10]
            today_processed = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM jobs
                    WHERE status IN ('preview_ready', 'completed')
                    AND substr(created_at, 1, 10) = ?
                    """,
                    (today,),
                ).fetchone()[0]
            )
            pending_review = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM evidence_segments es
                    WHERE NOT EXISTS (
                        SELECT 1 FROM review_decisions rd
                        WHERE rd.segment_id = es.segment_id
                        AND rd.decision IN ('accepted', 'rejected')
                    )
                    """
                ).fetchone()[0]
            )
            failed_route = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM sources
                    WHERE route_state IN (
                        'blocked_or_retry_later',
                        'failed_recoverable',
                        'failed_terminal',
                        'no_transcript',
                        'route_failed'
                    )
                    """
                ).fetchone()[0]
            )
            blocked_note_previews = int(
                conn.execute(
                    "SELECT COUNT(*) FROM note_previews WHERE write_allowed = 0"
                ).fetchone()[0]
            )
            route_states = {
                row["route_state"]: int(row["count"])
                for row in conn.execute(
                    "SELECT route_state, COUNT(*) AS count FROM sources GROUP BY route_state ORDER BY route_state"
                ).fetchall()
            }
            recent_jobs = [
                row_to_dict(row)
                for row in conn.execute(
                    """
                    SELECT j.job_id, j.source_id, s.title, s.route_state, j.stage, j.status,
                           j.progress, j.provider_call_count, j.media_download_count,
                           j.credential_reads, j.created_at
                    FROM jobs j
                    JOIN sources s ON s.source_id = j.source_id
                    ORDER BY j.created_at DESC, j.job_id DESC
                    LIMIT 5
                    """
                ).fetchall()
            ]
            note_targets = []
            for row in conn.execute(
                """
                SELECT target_id, adapter_type, root_path, permissions, write_mode
                FROM storage_targets
                ORDER BY target_id
                """
            ).fetchall():
                target = row_to_dict(row)
                target["path_exists"] = Path(str(target["root_path"])).expanduser().exists()
                note_targets.append(target)
            note_target_health = {
                "configured_count": len(note_targets),
                "preview_only_count": sum(1 for target in note_targets if target["write_mode"] == "preview_only"),
                "missing_path_count": sum(1 for target in note_targets if not target["path_exists"]),
                "targets": note_targets,
            }
            metrics = self.metrics()
        return {
            "ok": health["ok"],
            "read_only": True,
            "control_plane": {
                "today_processed": today_processed,
                "pending_review": pending_review,
                "failed_route": failed_route,
                "blocked_note_previews": blocked_note_previews,
                "recent_jobs": recent_jobs,
                "route_states": route_states,
            },
            "db_health": health,
            "note_target_health": note_target_health,
            "blocked_gates": {
                "writeback_allowed": False,
                "provider_runtime_allowed": False,
                "media_runtime_allowed": False,
                "scheduler_installed": False,
                "credential_reads_allowed": False,
            },
            "trust_counters": {
                "provider_call_count": 0,
                "media_download_count": 0,
                "credential_reads": 0,
                "source_note_writes": 0,
                "index_writes": 0,
                "queue_mutations": 0,
            },
            "metrics": metrics,
        }

    def source_detail_read_model(self, *, source_id: str) -> dict[str, Any]:
        """Return a complete read-only source identity and review summary."""
        if not source_id:
            raise AppStateError("source_id is required")
        with self.connect_read_only() as conn:
            source_row = conn.execute(
                """
                SELECT source_id, workspace_id, platform, canonical_url, canonical_id,
                       title, route_state, permission_state, created_at
                FROM sources
                WHERE source_id = ?
                """,
                (source_id,),
            ).fetchone()
            if source_row is None:
                raise AppStateError(f"source does not exist: {source_id}")
            source = row_to_dict(source_row)

            latest_job_row = conn.execute(
                """
                SELECT job_id, source_id, stage, status, progress, retry_count,
                       provider_call_count, media_download_count, credential_reads,
                       created_at
                FROM jobs
                WHERE source_id = ?
                ORDER BY created_at DESC, job_id DESC
                LIMIT 1
                """,
                (source_id,),
            ).fetchone()
            latest_job = row_to_dict(latest_job_row) if latest_job_row else {}

            evidence_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM evidence_segments WHERE source_id = ?",
                    (source_id,),
                ).fetchone()[0]
            )
            accepted_count = int(
                conn.execute(
                    """
                    SELECT COUNT(DISTINCT es.segment_id)
                    FROM evidence_segments es
                    JOIN review_decisions rd ON rd.segment_id = es.segment_id
                    WHERE es.source_id = ?
                      AND rd.decision = 'accepted'
                    """,
                    (source_id,),
                ).fetchone()[0]
            )
            rejected_count = int(
                conn.execute(
                    """
                    SELECT COUNT(DISTINCT es.segment_id)
                    FROM evidence_segments es
                    JOIN review_decisions rd ON rd.segment_id = es.segment_id
                    WHERE es.source_id = ?
                      AND rd.decision = 'rejected'
                    """,
                    (source_id,),
                ).fetchone()[0]
            )
            pending_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM evidence_segments es
                    WHERE es.source_id = ?
                      AND NOT EXISTS (
                        SELECT 1
                        FROM review_decisions rd
                        WHERE rd.segment_id = es.segment_id
                          AND rd.decision IN ('accepted', 'rejected')
                      )
                    """,
                    (source_id,),
                ).fetchone()[0]
            )
            warning_count = 0
            lanes: dict[str, int] = {}
            for row in conn.execute(
                """
                SELECT lane, warnings_json
                FROM evidence_segments
                WHERE source_id = ?
                """,
                (source_id,),
            ).fetchall():
                lane = str(row["lane"])
                lanes[lane] = lanes.get(lane, 0) + 1
                if parse_json_list(str(row["warnings_json"])):
                    warning_count += 1

        return {
            "ok": True,
            "read_only": True,
            "source": source,
            "latest_job": latest_job,
            "evidence_summary": {
                "evidence_count": evidence_count,
                "accepted_count": accepted_count,
                "pending_count": pending_count,
                "rejected_count": rejected_count,
                "warning_count": warning_count,
                "lanes": lanes,
            },
            "fallback_state": source_detail_fallback_state(str(source["route_state"])),
            "trust_counters": zero_trust_counters(),
        }

    @classmethod
    def local_library_read_model_for_workspace(
        cls,
        workspace_root: str | Path,
        *,
        index_path: str,
        query: str = "",
        limit: int = 50,
        category: str = "",
        source_type: str = "",
    ) -> dict[str, Any]:
        """Project one explicit local index file into the React library read model."""
        root = Path(workspace_root).expanduser().resolve()
        if not str(workspace_root).strip():
            raise AppStateError("workspace_root is required")
        if not root.exists() or not root.is_dir():
            raise AppStateError(f"workspace root does not exist: {root}")
        resolved_index_path = bounded_relative_child_path(root, index_path)
        try:
            bounded_limit = max(1, min(int(limit or 50), 200))
        except (TypeError, ValueError) as exc:
            raise AppStateError("limit must be an integer") from exc
        query_text = str(query or "").strip()
        category_filter = str(category or "").strip()
        source_type_filter = str(source_type or "").strip()

        index_exists = resolved_index_path.exists()
        if index_exists and not resolved_index_path.is_file():
            raise AppStateError(f"index path is not a file: {resolved_index_path}")
        records = load_local_library_index_records(resolved_index_path, root=root) if index_exists else []
        # Folder-scan fallback: surface the app's SOURCE notes (video/news) the index
        # misses — scoped to `type: source` notes, NOT a global Obsidian .md scan.
        records.extend(scan_folder_md_records(root, indexed_paths={r.get("path") for r in records if r.get("path")}))

        filtered_records = [
            record
            for record in records
            if local_library_filter_match(record, category=category_filter, source_type=source_type_filter)
        ]
        projected_records = []
        matched_count = 0
        for record in filtered_records:
            matched = local_library_query_match(record, query_text)
            if matched:
                matched_count += 1
            projected_records.append({**record, "matched": matched})

        local_folder = str(resolved_index_path.parent.relative_to(root))
        read_model = {
            "schema_id": "yt-react-local-library-index-read-model-v1",
            "storage_mode": "local_read_model_preview_only",
            "local_folder": "." if local_folder == "." else local_folder,
            "target_index_path": resolved_index_path.relative_to(root).as_posix(),
            "keyword_query": query_text,
            "record_count": len(filtered_records),
            "matched_count": matched_count,
            "records": projected_records[:bounded_limit],
            "allowed_record_sources": ["existing_local_index"],
            "idempotency_key_fields": ["source_type", "path", "title"],
            # Local-first product: the library intentionally scans the user's own
            # chosen folder for .md (index + folder-scan fallback). Read-only — it
            # never writes notes/index or syncs externally.
            "filesystem_scan_allowed": True,
            "source_note_writes": 0,
            "index_writes": 0,
            "external_api_sync_allowed": False,
            "credential_reads": 0,
            "boundary": "index_plus_local_folder_scan_read_only_no_write",
        }
        return {
            "ok": True,
            "read_only": True,
            "route_schema_id": "yt-react-local-library-readonly-route-v1",
            "read_model": read_model,
            "search_summary": {
                "query": query_text,
                "category": category_filter,
                "source_type": source_type_filter,
                "record_count": len(filtered_records),
                "matched_count": matched_count,
                "index_exists": index_exists,
            },
            "trust_counters": local_library_zero_trust_counters(),
        }

    def evidence_review_decision_state_read_model(self, *, source_id: str) -> dict[str, Any]:
        """Return read-only segment review decision state for a source."""
        if not source_id:
            raise AppStateError("source_id is required")
        if not self.db_path.exists():
            return empty_evidence_review_decision_state_payload(
                self.workspace_root,
                source_id=source_id,
                state="missing_db",
                ok=False,
                database_exists=False,
            )

        with self.connect_read_only() as conn:
            source_row = conn.execute(
                """
                SELECT source_id, workspace_id, platform, canonical_url, canonical_id,
                       title, route_state, permission_state, created_at
                FROM sources
                WHERE source_id = ?
                """,
                (source_id,),
            ).fetchone()
            if source_row is None:
                return empty_evidence_review_decision_state_payload(
                    self.workspace_root,
                    source_id=source_id,
                    state="source_not_found",
                    ok=False,
                    database_exists=True,
                )
            source = row_to_dict(source_row)

            rows = conn.execute(
                """
                SELECT es.segment_id, es.source_id, es.lane, es.timestamp_start,
                       es.timestamp_end, es.text, es.confidence, es.warnings_json,
                       rd.decision_id, rd.decision, rd.reviewer_note, rd.decided_at
                FROM evidence_segments es
                LEFT JOIN review_decisions rd
                  ON rd.segment_id = es.segment_id
                 AND NOT EXISTS (
                    SELECT 1
                    FROM review_decisions newer
                    WHERE newer.segment_id = rd.segment_id
                      AND (
                        newer.decided_at > rd.decided_at
                        OR (newer.decided_at = rd.decided_at AND newer.decision_id > rd.decision_id)
                      )
                 )
                WHERE es.source_id = ?
                ORDER BY es.timestamp_start, es.segment_id
                """,
                (source_id,),
            ).fetchall()

        segments = []
        accepted_count = 0
        pending_count = 0
        rejected_count = 0
        warning_count = 0
        writeback_eligible_count = 0
        for row in rows:
            warnings = parse_json_list(str(row["warnings_json"]))
            decision = str(row["decision"] or "pending")
            writeback_eligible = decision == "accepted"
            if decision == "accepted":
                accepted_count += 1
            elif decision == "rejected":
                rejected_count += 1
            else:
                pending_count += 1
                decision = "pending"
            if warnings:
                warning_count += 1
            if writeback_eligible:
                writeback_eligible_count += 1
            segments.append(
                {
                    "segment_id": row["segment_id"],
                    "lane": row["lane"],
                    "timestamp_start": row["timestamp_start"],
                    "timestamp_end": row["timestamp_end"],
                    "text": row["text"],
                    "confidence": row["confidence"],
                    "warnings": warnings,
                    "decision": decision,
                    "decision_id": row["decision_id"] or "",
                    "reviewed_at": row["decided_at"] or "",
                    "reviewer": "operator" if row["decision_id"] else "",
                    "decision_source": "review_decisions" if row["decision_id"] else "decision_absent_state",
                    "writeback_eligible": writeback_eligible,
                }
            )

        evidence_count = len(segments)
        fallback_state = source_detail_fallback_state(str(source["route_state"]))
        blocked_writeback_reasons = evidence_review_blocked_writeback_reasons(
            evidence_count=evidence_count,
            accepted_count=accepted_count,
            pending_count=pending_count,
            fallback_required=bool(fallback_state["fallback_required"]),
        )
        review_state = evidence_review_readiness_state(
            evidence_count=evidence_count,
            accepted_count=accepted_count,
            pending_count=pending_count,
            blocked_writeback_reasons=blocked_writeback_reasons,
        )

        return {
            "ok": True,
            "read_only": True,
            "source_id": source_id,
            "source": source,
            "review_readiness": {
                "state": review_state,
                "operator_review_required": pending_count > 0 or evidence_count == 0,
                "decision_state_complete": pending_count == 0 and evidence_count > 0,
                "writeback_ready": accepted_count > 0 and not blocked_writeback_reasons,
                "blocked_reasons": blocked_writeback_reasons,
            },
            "summary": {
                "evidence_count": evidence_count,
                "accepted_count": accepted_count,
                "pending_count": pending_count,
                "rejected_count": rejected_count,
                "warning_count": warning_count,
                "writeback_eligible_count": writeback_eligible_count,
            },
            "segments": segments,
            "route_action_recovery_state": evidence_review_route_action_recovery_state(str(source["route_state"])),
            "blocked_writeback_reasons": blocked_writeback_reasons,
            "trust_counters": zero_trust_counters(),
        }

    def retained_artifact_read_model(self) -> dict[str, Any]:
        """Return retained development evidence without production notebook mixing."""
        with self.connect_read_only() as conn:
            rows = conn.execute(
                """
                SELECT n.note_id, n.source_id, n.target_id, n.path, n.previous_hash,
                       n.current_hash, n.write_status, n.idempotency_key, n.created_at,
                       s.platform, s.canonical_id, s.title
                FROM notes n
                JOIN sources s ON s.source_id = n.source_id
                WHERE n.path LIKE ?
                ORDER BY n.created_at DESC, n.note_id DESC
                """,
                ("%/_writeback_smoke/%",),
            ).fetchall()
            artifacts = []
            for row in rows:
                artifact = row_to_dict(row)
                note_path = Path(str(artifact["path"]))
                note_hash = sha256_file_text(note_path)
                rollback_rows = conn.execute(
                    """
                    SELECT rollback_id, previous_hash, rollback_action,
                           action_status, created_at
                    FROM rollbacks
                    WHERE note_id = ?
                    ORDER BY created_at DESC, rollback_id DESC
                    """,
                    (artifact["note_id"],),
                ).fetchall()
                smoke_index_path = note_path.parent / "_youtube_index_smoke.json"
                artifact.update(
                    {
                        "artifact_type": "development_writeback_smoke_note",
                        "retention_mode": "keep_for_development_evidence",
                        "note_exists": note_path.exists(),
                        "note_hash": note_hash,
                        "hash_matches_sqlite": note_hash == artifact["current_hash"],
                        "smoke_path": "_writeback_smoke" in note_path.parts,
                        "smoke_index_path": str(smoke_index_path),
                        "smoke_index_exists": smoke_index_path.exists(),
                        "rollback_visible": bool(rollback_rows),
                        "rollback_refs": [row_to_dict(rollback) for rollback in rollback_rows],
                        "production_exclusion": {
                            "production_content": False,
                            "youtube_index_allowed": False,
                            "normal_notebook_item": False,
                            "ai_summary_input_allowed": False,
                            "cleanup_allowed_without_approval": False,
                        },
                    }
                )
                artifacts.append(artifact)
        return {
            "ok": True,
            "read_only": True,
            "retention_mode": "keep_for_development_evidence",
            "retained_artifact_count": len(artifacts),
            "retained_artifacts": artifacts,
            "production_exclusion_guard": {
                "smoke_note_is_production_content": False,
                "production_index_update_allowed": False,
                "normal_notebook_item": False,
                "ai_summary_input_allowed": False,
                "cleanup_allowed": False,
                "rollback_allowed": False,
                "archive_allowed": False,
                "additional_write_allowed": False,
            },
            "trust_counters": zero_trust_counters(),
        }

    @classmethod
    def resume_read_model_for_workspace(
        cls,
        workspace_root: str | Path,
        *,
        mode: str = "last_active",
    ) -> dict[str, Any]:
        root = Path(workspace_root).expanduser().resolve()
        runtime = cls(root)
        if not root.exists():
            return empty_resume_payload(root, mode=mode, reason="workspace_root_missing")
        if not runtime.db_path.exists():
            return empty_resume_payload(root, mode=mode, reason="workspace_database_missing")
        return runtime.resume_read_model(mode=mode)

    def resume_read_model(self, *, mode: str = "last_active") -> dict[str, Any]:
        """Return the app resume snapshot without mutating SQLite."""
        if mode not in {"last_active"}:
            raise AppStateError(f"unsupported resume mode: {mode}")
        with self.connect_read_only() as conn:
            workspace = self._latest_workspace(conn)
            if not workspace:
                return empty_resume_payload(self.workspace_root, mode=mode, reason="workspace_row_missing")

            last_job = self._select_resume_job(conn)
            last_source = {}
            accepted_evidence: list[dict[str, Any]] = []
            note_draft: dict[str, Any] = {}
            if last_job:
                last_source = self._source_for_job(conn, str(last_job["job_id"]))
                if last_source:
                    accepted_evidence = self._accepted_evidence_for_source(
                        conn,
                        str(last_source["source_id"]),
                    )
                    note_draft = self._latest_note_preview_for_source(
                        conn,
                        str(last_source["source_id"]),
                    )

            control_plane = self._control_plane_summary(conn)
            note_target_health = self._note_target_health(conn)
            return {
                "ok": True,
                "read_only": True,
                "empty_state": False,
                "mode": mode,
                "resume_snapshot": {
                    "workspace": workspace,
                    "last_source": last_source,
                    "last_job": last_job,
                    "accepted_evidence": accepted_evidence,
                    "note_draft": note_draft,
                    "failed_routes": self._failed_routes(conn),
                    "approval_gates": resume_approval_gates(),
                    "rollback_refs": self._rollback_refs(conn),
                    "resume_recommendation": self._resume_recommendation(last_job),
                },
                "control_plane_summary": control_plane,
                "ui_restore_targets": resume_ui_restore_targets(),
                "blocked_gates": resume_blocked_gates(),
                "trust_counters": zero_trust_counters(),
                "db_health": {
                    "ok": True,
                    "workspace_root": str(self.workspace_root),
                    "db_path": str(self.db_path),
                    "database_exists": True,
                    "schema_version": self._schema_version(conn),
                    "read_only": True,
                    **zero_trust_counters(),
                },
                "note_target_health": note_target_health,
            }

    def _resume_recommendation(self, last_job: dict[str, Any]) -> dict[str, Any]:
        """Derive the next resume action from the selected job's durable lifecycle state."""
        retry_count = int(last_job.get("retry_count", 0)) if last_job else 0
        retries_remaining = max(0, MAX_JOB_RETRIES - retry_count)
        status = str(last_job.get("status", "")) if last_job else ""
        if not last_job:
            action, resumable, reason = "none", False, "no_job"
        elif status == "failed_terminal":
            action, resumable, reason = "blocked_retry_exhausted", False, "retry limit reached"
        elif status == "failed_recoverable":
            if retries_remaining > 0:
                action, resumable, reason = "retry", True, "recoverable failure with retries remaining"
            else:
                action, resumable, reason = "blocked_retry_exhausted", False, "no retries remaining"
        elif status == "needs_review":
            action, resumable, reason = "continue_review", True, "evidence awaits review"
        elif status == "preview_ready":
            action, resumable, reason = "open_preview", True, "note preview ready"
        elif status == "completed":
            action, resumable, reason = "none", False, "job completed"
        else:
            action, resumable, reason = "continue", True, "job in flight"
        return {
            "resumable": resumable,
            "action": action,
            "reason": reason,
            "retry_count": retry_count,
            "retry_limit": MAX_JOB_RETRIES,
            "retries_remaining": retries_remaining,
        }

    def _latest_workspace(self, conn: sqlite3.Connection) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM workspaces ORDER BY created_at DESC, workspace_id DESC LIMIT 1"
        ).fetchone()
        return row_to_dict(row) if row else {}

    def _schema_version(self, conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        return str(row["value"]) if row else ""

    def _select_resume_job(self, conn: sqlite3.Connection) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT j.job_id, j.source_id, j.stage, j.status, j.progress,
                   j.retry_count, j.provider_call_count, j.media_download_count,
                   j.credential_reads, j.input_state_hash, j.output_state_hash,
                   j.created_at, s.title, s.route_state, s.canonical_url, s.canonical_id
            FROM jobs j
            JOIN sources s ON s.source_id = j.source_id
            ORDER BY
                CASE
                    WHEN j.status = 'preview_ready' THEN 0
                    WHEN s.route_state IN ('route_failed', 'no_transcript', 'failed_recoverable', 'failed_terminal', 'blocked_or_retry_later') THEN 1
                    ELSE 2
                END,
                j.created_at DESC,
                j.job_id DESC
            LIMIT 1
            """
        ).fetchone()
        return row_to_dict(row) if row else {}

    def _source_for_job(self, conn: sqlite3.Connection, job_id: str) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT s.*
            FROM sources s
            JOIN jobs j ON j.source_id = s.source_id
            WHERE j.job_id = ?
            """,
            (job_id,),
        ).fetchone()
        return row_to_dict(row) if row else {}

    def _accepted_evidence_for_source(self, conn: sqlite3.Connection, source_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT es.segment_id, es.source_id, es.lane, es.timestamp_start,
                   es.timestamp_end, es.text, es.confidence, es.warnings_json,
                   es.source_hash, rd.decision, rd.reviewer_note, rd.decided_at
            FROM evidence_segments es
            JOIN review_decisions rd ON rd.segment_id = es.segment_id
            WHERE es.source_id = ?
              AND rd.decision = 'accepted'
            ORDER BY es.timestamp_start, es.segment_id, rd.decided_at DESC
            """,
            (source_id,),
        ).fetchall()
        evidence = []
        seen: set[str] = set()
        for row in rows:
            item = row_to_dict(row)
            segment_id = str(item["segment_id"])
            if segment_id in seen:
                continue
            seen.add(segment_id)
            item["warnings"] = parse_json_list(str(item.pop("warnings_json", "[]")))
            evidence.append(item)
        return evidence

    def _latest_note_preview_for_source(self, conn: sqlite3.Connection, source_id: str) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT np.preview_id, np.source_id, np.target_id, np.template_id,
                   np.output_hash, np.write_allowed, np.write_block_reason,
                   np.accepted_segment_ids_json, np.created_at,
                   st.adapter_type, st.root_path, st.permissions, st.write_mode
            FROM note_previews np
            JOIN storage_targets st ON st.target_id = np.target_id
            WHERE np.source_id = ?
            ORDER BY np.created_at DESC, np.preview_id DESC
            LIMIT 1
            """,
            (source_id,),
        ).fetchone()
        if not row:
            return {}
        preview = row_to_dict(row)
        preview["accepted_segment_ids"] = parse_json_list(str(preview.pop("accepted_segment_ids_json", "[]")))
        return preview

    def _failed_routes(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT source_id, platform, canonical_url, canonical_id, title,
                   route_state, permission_state, created_at
            FROM sources
            WHERE route_state IN (
                'blocked_or_retry_later',
                'failed_recoverable',
                'failed_terminal',
                'no_transcript',
                'route_failed'
            )
            ORDER BY created_at DESC, source_id DESC
            LIMIT 5
            """
        ).fetchall()
        return [row_to_dict(row) for row in rows]

    def _rollback_refs(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT rollback_id, note_id, previous_hash, rollback_action,
                   action_status, created_at
            FROM rollbacks
            ORDER BY created_at DESC, rollback_id DESC
            LIMIT 5
            """
        ).fetchall()
        return [row_to_dict(row) for row in rows]

    def _control_plane_summary(self, conn: sqlite3.Connection) -> dict[str, Any]:
        today = utc_now()[:10]
        today_processed = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE status IN ('preview_ready', 'completed')
                AND substr(created_at, 1, 10) = ?
                """,
                (today,),
            ).fetchone()[0]
        )
        pending_review = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM evidence_segments es
                WHERE NOT EXISTS (
                    SELECT 1 FROM review_decisions rd
                    WHERE rd.segment_id = es.segment_id
                    AND rd.decision IN ('accepted', 'rejected')
                )
                """
            ).fetchone()[0]
        )
        failed_route = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM sources
                WHERE route_state IN (
                    'blocked_or_retry_later',
                    'failed_recoverable',
                    'failed_terminal',
                    'no_transcript',
                    'route_failed'
                )
                """
            ).fetchone()[0]
        )
        blocked_note_previews = int(
            conn.execute("SELECT COUNT(*) FROM note_previews WHERE write_allowed = 0").fetchone()[0]
        )
        return {
            "today_processed": today_processed,
            "pending_review": pending_review,
            "failed_route": failed_route,
            "blocked_note_previews": blocked_note_previews,
        }

    def _note_target_health(self, conn: sqlite3.Connection) -> dict[str, Any]:
        rows = conn.execute(
            """
            SELECT target_id, adapter_type, root_path, permissions, write_mode
            FROM storage_targets
            ORDER BY target_id
            """
        ).fetchall()
        targets = []
        for row in rows:
            target = row_to_dict(row)
            target["path_exists"] = Path(str(target["root_path"])).expanduser().exists()
            targets.append(target)
        return {
            "configured_count": len(targets),
            "preview_only_count": sum(1 for target in targets if target["write_mode"] == "preview_only"),
            "missing_path_count": sum(1 for target in targets if not target["path_exists"]),
            "targets": targets,
        }

    def _insert_evidence_segment(
        self,
        conn: sqlite3.Connection,
        source_id: str,
        segment: dict[str, Any],
        index: int,
    ) -> None:
        lane = str(segment.get("lane") or "native_caption")
        text = str(segment.get("text") or "")
        segment_id = str(segment.get("segment_id") or stable_id("seg", source_id, lane, index, text))
        warnings = segment.get("warnings") if isinstance(segment.get("warnings"), list) else []
        conn.execute(
            """
            INSERT OR IGNORE INTO evidence_segments(
                segment_id, source_id, lane, timestamp_start, timestamp_end,
                text, confidence, warnings_json, source_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                segment_id,
                source_id,
                lane,
                float(segment.get("timestamp_start", 0)),
                float(segment.get("timestamp_end", 0)),
                text,
                float(segment.get("confidence", 1.0)),
                json.dumps(warnings, ensure_ascii=False),
                str(segment.get("source_hash") or sha256_text(text)),
            ),
        )

    def _get_one(self, conn: sqlite3.Connection, query: str, *params: object) -> dict[str, Any]:
        row = conn.execute(query, params).fetchone()
        if row is None:
            raise AppStateError("expected row was not found")
        return row_to_dict(row)

    def _require_workspace(self, conn: sqlite3.Connection, workspace_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone()
        if row is None:
            raise AppStateError(f"workspace does not exist: {workspace_id}")
        return row_to_dict(row)

    def _require_source(self, conn: sqlite3.Connection, source_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        if row is None:
            raise AppStateError(f"source does not exist: {source_id}")
        return row_to_dict(row)

    def _require_target(self, conn: sqlite3.Connection, target_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM storage_targets WHERE target_id = ?", (target_id,)).fetchone()
        if row is None:
            raise AppStateError(f"storage target does not exist: {target_id}")
        return row_to_dict(row)

    def _require_segment(self, conn: sqlite3.Connection, segment_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM evidence_segments WHERE segment_id = ?", (segment_id,)).fetchone()
        if row is None:
            raise AppStateError(f"evidence segment does not exist: {segment_id}")
        return row_to_dict(row)

    def _require_accepted_decision(self, conn: sqlite3.Connection, segment_id: str) -> None:
        row = conn.execute(
            "SELECT 1 FROM review_decisions WHERE segment_id = ? AND decision = 'accepted'",
            (segment_id,),
        ).fetchone()
        if row is None:
            raise AppStateError(f"segment is not accepted: {segment_id}")


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    if "write_allowed" in result:
        result["write_allowed"] = bool(result["write_allowed"])
    return result


def parse_json_list(value: str) -> list[Any]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def evidence_review_blocked_writeback_reasons(
    *,
    evidence_count: int,
    accepted_count: int,
    pending_count: int,
    fallback_required: bool,
) -> list[str]:
    reasons = ["writeback_requires_separate_approval"]
    if evidence_count == 0:
        reasons.append("no_evidence_segments")
    if accepted_count == 0:
        reasons.append("no_accepted_segments")
    if pending_count > 0:
        reasons.append("pending_review_segments")
    if fallback_required:
        reasons.append("route_fallback_required")
    return reasons


def evidence_review_readiness_state(
    *,
    evidence_count: int,
    accepted_count: int,
    pending_count: int,
    blocked_writeback_reasons: list[str],
) -> str:
    if evidence_count == 0:
        return "no_evidence"
    if pending_count > 0:
        return "pending_review"
    if accepted_count > 0 and blocked_writeback_reasons == ["writeback_requires_separate_approval"]:
        return "writeback_blocked"
    return "review_complete_no_writeback_candidate"


def evidence_review_route_action_recovery_state(route_state: str) -> dict[str, Any]:
    fallback_state = source_detail_fallback_state(route_state)
    return {
        "fallback_required": fallback_state["fallback_required"],
        "fallback_reason": fallback_state["fallback_reason"],
        "manual_evidence_allowed": bool(fallback_state["fallback_required"]),
        "asr_gate_state": fallback_state["asr_gate_state"],
        "provider_media_allowed": False,
        "operator_action_required": bool(fallback_state["fallback_required"]),
    }


def empty_evidence_review_decision_state_payload(
    workspace_root: str | Path,
    *,
    source_id: str,
    state: str,
    ok: bool,
    database_exists: bool,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "read_only": True,
        "source_id": source_id,
        "source": {},
        "review_readiness": {
            "state": state,
            "operator_review_required": True,
            "decision_state_complete": False,
            "writeback_ready": False,
            "blocked_reasons": [state, "writeback_requires_separate_approval"],
        },
        "summary": {
            "evidence_count": 0,
            "accepted_count": 0,
            "pending_count": 0,
            "rejected_count": 0,
            "warning_count": 0,
            "writeback_eligible_count": 0,
        },
        "segments": [],
        "route_action_recovery_state": {
            "fallback_required": False,
            "fallback_reason": state,
            "manual_evidence_allowed": False,
            "asr_gate_state": "closed_until_source_exists",
            "provider_media_allowed": False,
            "operator_action_required": True,
        },
        "blocked_writeback_reasons": [state, "writeback_requires_separate_approval"],
        "trust_counters": zero_trust_counters(),
        "db_health": {
            "ok": False,
            "workspace_root": str(Path(workspace_root).expanduser().resolve()),
            "database_exists": database_exists,
            "read_only": True,
        },
    }


def bounded_child_path(root_path: str, child_path: str) -> Path:
    root = Path(root_path).expanduser().resolve()
    child = Path(child_path).expanduser()
    resolved = child.resolve() if child.is_absolute() else (root / child).resolve()
    if resolved != root and root not in resolved.parents:
        raise AppStateError(f"path must stay inside storage target root: {resolved}")
    return resolved


def bounded_relative_child_path(root_path: str | Path, child_path: str) -> Path:
    if not str(child_path or "").strip():
        raise AppStateError("index_path is required")
    child = Path(str(child_path)).expanduser()
    if child.is_absolute():
        raise AppStateError("index_path must be relative")
    if ".." in child.parts:
        raise AppStateError("index_path must not contain path traversal")
    return bounded_child_path(str(root_path), child.as_posix())


def load_local_library_index_records(index_path: Path, *, root: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AppStateError(f"local library index json is invalid: {index_path}") from exc
    if isinstance(data, list):
        raw_items = data
    elif isinstance(data, dict):
        raw_items = []
        if isinstance(data.get("records"), list):
            raw_items.extend(data["records"])
        if isinstance(data.get("items"), dict):
            raw_items.extend(data["items"].values())
        if isinstance(data.get("videos"), dict):
            raw_items.extend(data["videos"].values())
    else:
        raise AppStateError("local library index json root must be object or list")
    records: list[dict[str, Any]] = []
    for raw in raw_items:
        if isinstance(raw, dict):
            records.append(normalize_local_library_record(raw, root=root))
    return records


_SCAN_FILE_CAP = 2000


def _scan_first(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


_RECENCY_KEYS = ("date", "clipped_at", "published", "status_changed_at", "updated")


def _note_recency(head: str, md: Path) -> str:
    for key in _RECENCY_KEYS:
        value = _scan_first(rf"(?m)^{key}:\s*\"?([0-9][0-9 :\-/]+)", head)
        if value:
            return value.strip()
    try:
        return datetime.fromtimestamp(md.stat().st_mtime, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    except OSError:
        return ""


def list_source_subfolders(vault_root: str, sources_dirname: str = "02_Sources") -> list[dict[str, str]]:
    """List source folders under <vault_root>/02_Sources for the value library's
    default aggregation. Read-only; skips hidden/underscore dirs (_attachments)."""
    sources = Path(str(vault_root or "")).expanduser() / sources_dirname
    if not sources.is_dir():
        return []
    return [
        {"name": child.name, "path": child.as_posix()}
        for child in sorted(sources.iterdir())
        if child.is_dir() and not child.name.startswith((".", "_"))
    ]


def aggregate_value_notes(
    folders: list[str], *, query: str = "", sort: str = "recency", limit: int = 300
) -> dict[str, Any]:
    """V1 cross-source value library: aggregate .md across an allowlist of folders
    (YT / atomic / github / daily / manual …), tag each by its source folder, drop
    index files. Read-only — no writes, no global vault scan.

    V2 sort modes:
      - "recency" (default): substring-filter by query, newest-first (V1 behaviour).
      - "relevance": with a query, rank by stdlib keyword/tag overlap — query terms
        weighted by field (title ×3, tags/category ×2, summary ×1), score>0 only,
        recency as tie-break. Empty query falls back to recency (no signal)."""
    query_text = str(query or "").strip().lower()
    mode = "relevance" if str(sort or "").strip().lower() == "relevance" else "recency"
    terms = [t for t in re.split(r"\s+", query_text) if t] if query_text else []
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    for folder_text in folders:
        folder = Path(folder_text).expanduser()
        if not folder.is_dir():
            continue
        source_label = folder.name
        for md in sorted(folder.rglob("*.md"))[:_SCAN_FILE_CAP]:
            abs_path = str(md.resolve())
            if abs_path in seen:
                continue
            seen.add(abs_path)
            try:
                head = md.read_text(encoding="utf-8", errors="ignore")[:4000]
            except OSError:
                continue
            if re.search(r"(?m)^type:\s*index\b", head):
                continue  # skip index/aggregate files, keep real notes
            title = _scan_first(r"(?m)^title:\s*\"?(.+?)\"?\s*$", head) or _scan_first(r"(?m)^#\s+(.+)$", head) or md.stem
            category = _scan_first(r"(?m)^(?:category|分類)\s*[:：]\s*(.+)$", head) or "未分類"
            source_url = _scan_first(r"(?m)^(?:source_url|original_url|url)\s*[:：]\s*\"?(.+?)\"?\s*$", head)
            tags = _scan_first(r"(?m)^tags:\s*(.+)$", head)
            summary = _scan_first(r"(?m)^summary:\s*(.+)$", head)
            record = {
                "title": title,
                "category": category,
                "source": source_label,
                "path": md.relative_to(folder).as_posix(),
                "vault_path": str(folder),
                "source_url": source_url,
                "recency": _note_recency(head, md),
                "source_id": abs_path,
            }
            if mode == "relevance" and terms:
                score = _relevance_score(terms, title=title, tags=f"{tags} {category}", summary=summary)
                if score <= 0:
                    continue  # relevance mode shows only notes that overlap the query
                record["score"] = score
            elif query_text and query_text not in f"{title} {category} {source_label}".lower():
                continue
            records.append(record)
    if mode == "relevance" and terms:
        records.sort(key=lambda r: (r.get("score", 0), r["recency"]), reverse=True)
    else:
        records.sort(key=lambda r: r["recency"], reverse=True)
    records = records[: max(1, min(int(limit or 300), 1000))]
    sources: dict[str, int] = {}
    for record in records:
        sources[record["source"]] = sources.get(record["source"], 0) + 1
    return {"records": records, "sources": sources, "total": len(records)}


def _relevance_score(terms: list[str], *, title: str, tags: str, summary: str) -> int:
    """Stdlib keyword/tag overlap: each query term scores per field it hits —
    title ×3, tags/category ×2, summary ×1 — summed across terms (TF-IDF-ish)."""
    title_l, tags_l, summary_l = title.lower(), tags.lower(), summary.lower()
    score = 0
    for term in terms:
        if term in title_l:
            score += 3
        if term in tags_l:
            score += 2
        if term in summary_l:
            score += 1
    return score


def _is_source_note(head: str) -> bool:
    # Scope the scan to the app's SOURCE notes (video / news etc.), not arbitrary
    # Obsidian markdown. App notes carry `type: source` frontmatter or the AI block.
    return bool(re.search(r"(?m)^type:\s*source\b", head)) or "vaultwiki:ai:start" in head


def scan_folder_md_records(root: Path, *, indexed_paths: set[str]) -> list[dict[str, Any]]:
    """Project SOURCE-note .md files (video/news) not covered by the index into
    library records, so an existing folder is browsable. Plain Obsidian markdown
    without the source marker is intentionally skipped (not a global md scan)."""
    out: list[dict[str, Any]] = []
    for md in sorted(root.rglob("*.md"))[:_SCAN_FILE_CAP]:
        rel = md.relative_to(root).as_posix()
        try:
            head = md.read_text(encoding="utf-8", errors="ignore")[:4000]
        except OSError:
            continue
        if not _is_source_note(head):
            continue
        title = _scan_first(r"(?m)^title:\s*(.+)$", head) or _scan_first(r"(?m)^#\s+(.+)$", head) or md.stem
        category = _scan_first(r"(?m)^(?:category|分類)\s*[:：]\s*(.+)$", head) or "未分類"
        source_url = _scan_first(r"(?m)^(?:source_url|original_url|url)\s*[:：]\s*(.+)$", head)
        source_type = _scan_first(r"(?m)^source_type:\s*(.+)$", head)
        record = normalize_local_library_record(
            {"title": title, "path": rel, "category": category, "source_id": rel,
             "source_url": source_url, "source_type": source_type},
            root=root,
        )
        if record.get("path") in indexed_paths:
            continue
        out.append(record)
    return out


def normalize_local_library_record(raw: dict[str, Any], *, root: Path) -> dict[str, Any]:
    platform = str(raw.get("platform") or raw.get("source") or infer_platform(raw)).strip() or "youtube"
    source_type = normalize_source_type(str(raw.get("source_type") or raw.get("type") or ""), platform)
    reviewed_evidence = raw.get("reviewed_evidence") if isinstance(raw.get("reviewed_evidence"), dict) else {}
    source_id = str(raw.get("source_id") or raw.get("video_id") or raw.get("canonical_id") or "").strip()
    canonical_id = str(raw.get("canonical_id") or raw.get("video_id") or source_id).strip()
    path = str(
        raw.get("path")
        or raw.get("note_path")
        or raw.get("relativePath")
        or raw.get("relative_path")
        or reviewed_evidence.get("note_path")
        or ""
    ).strip()
    if path:
        path = local_library_record_path(path, root=root)
    keywords = normalize_keywords(raw.get("keywords") or raw.get("tags") or raw.get("extraction_sources") or [])
    title = str(raw.get("title") or raw.get("name") or canonical_id or source_id or "Untitled").strip()
    source_url = str(
        raw.get("source_url")
        or raw.get("canonical_url")
        or raw.get("original_url")
        or raw.get("url")
        or ""
    ).strip()
    reviewed_note_path = str(reviewed_evidence.get("note_path") or path or "").strip()
    reviewed_note_path = local_library_record_path(reviewed_note_path, root=root) if reviewed_note_path else path
    accepted_segment_count = int(reviewed_evidence.get("accepted_segment_count") or raw.get("reviewed_evidence_count") or 0)
    preview_id = str(reviewed_evidence.get("preview_id") or "").strip()
    write_preview_id = str(reviewed_evidence.get("write_preview_id") or "").strip()
    current_hash = str(reviewed_evidence.get("current_hash") or raw.get("current_hash") or raw.get("content_hash") or "").strip()
    evidence_lane = str(reviewed_evidence.get("evidence_lane") or "").strip()
    if not evidence_lane:
        evidence_lane = "local_asr" if preview_id or "local_asr" in " ".join(keywords).lower() else ""
    review_status = "accepted" if accepted_segment_count > 0 else str(raw.get("reviewed_evidence_status") or "").strip()
    index_status = "indexed" if path else "not_indexed"
    writeback_status = "written_indexed" if reviewed_note_path and current_hash else "not_written"
    rollback_available = bool(preview_id and current_hash and reviewed_note_path)
    completion_candidate = bool(accepted_segment_count > 0 and reviewed_note_path and current_hash and index_status == "indexed")
    completion_status = (
        "completed"
        if completion_candidate and rollback_available
        else "completed_with_rollback_proof_pending"
        if completion_candidate
        else "not_completed"
    )
    completion_blocked_reason = "" if rollback_available else "rollback_proof_not_materialized"
    source_note_detail = {
        "schema_id": "yt-react-source-note-detail-read-model-v1",
        "source": {
            "source_id": source_id,
            "canonical_id": canonical_id,
            "source_url": source_url,
            "platform": platform,
            "title": title,
        },
        "note": {
            "path": reviewed_note_path,
            "current_hash": current_hash,
            "index_status": index_status,
            "writeback_status": writeback_status,
        },
        "evidence": {
            "lane": evidence_lane,
            "review_status": review_status,
            "accepted_segment_count": accepted_segment_count,
            "accepted_segment_ids": ["local_asr:transcript_preview"] if evidence_lane == "local_asr" and accepted_segment_count else [],
            "preview_id": preview_id,
            "write_preview_id": write_preview_id,
        },
        "completion": {
            "source_to_note_visible": completion_candidate,
            "source_to_note_completed": completion_candidate,
            "completion_candidate": completion_candidate,
            "completion_status": completion_status,
            "completion_blocked_reason": completion_blocked_reason,
        },
        "rollback": {
            "available": rollback_available,
            "execution_allowed": False,
            "display_only": True,
        },
        "trust_counters": {
            "source_note_writes": 0,
            "index_writes": 0,
            "sqlite_mutations": 0,
            "provider_call_count": 0,
            "media_download_count": 0,
            "credential_reads": 0,
            "rollback_executions": 0,
        },
    }
    return {
        "source_type": source_type,
        "platform": platform,
        "source_id": source_id,
        "canonical_id": canonical_id,
        "title": title,
        "source_url": source_url,
        "path": path,
        "status": str(raw.get("status") or "ready").strip(),
        "matched": False,
        "category": str(raw.get("category") or raw.get("content_category") or "未分類").strip(),
        "keywords": keywords,
        "source_note_detail": source_note_detail,
    }


def infer_platform(raw: dict[str, Any]) -> str:
    url = str(raw.get("canonical_url") or raw.get("original_url") or raw.get("source_url") or raw.get("url") or "")
    lowered = url.lower()
    if "youtube.com" in lowered or "youtu.be" in lowered:
        return "youtube"
    if "instagram.com" in lowered:
        return "instagram"
    if "threads.net" in lowered:
        return "threads"
    if "twitter.com" in lowered or "x.com" in lowered:
        return "x"
    return "local"


def local_library_record_path(path: str, *, root: Path) -> str:
    note_path = Path(path).expanduser()
    if note_path.is_absolute():
        resolved = note_path.resolve()
        if resolved == root:
            return "."
        if root in resolved.parents:
            return resolved.relative_to(root).as_posix()
        return resolved.as_posix()
    rel = note_path.as_posix()
    # Self-heal stale index prefixes: entries written against an older/parent
    # vault root (e.g. "note_study/02_Sources/youtube/x.md" or
    # "02_Sources/youtube/videos/x.md") while this index lives inside the
    # youtube folder itself. A mismatched prefix made the same note appear
    # twice (index record + folder-scan record). Strip leading segments until
    # the file actually exists under root.
    if rel and not (root / rel).exists():
        parts = rel.split("/")
        for start in range(1, len(parts)):
            candidate = "/".join(parts[start:])
            if (root / candidate).exists():
                return candidate
    return rel


def normalize_source_type(value: str, platform: str) -> str:
    normalized = value.strip()
    if platform == "youtube" and normalized in {"", "video", "short", "shorts", "youtube"}:
        return "YT"
    if platform == "instagram" and normalized in {"", "reel", "reels", "instagram"}:
        return "Reels"
    if platform == "threads" and normalized in {"", "thread", "threads"}:
        return "Threads"
    if platform == "x" and normalized in {"", "twitter", "tweet"}:
        return "X"
    return normalized or platform.upper()


def normalize_keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    return []


def local_library_filter_match(record: dict[str, Any], *, category: str, source_type: str) -> bool:
    if category and category.casefold() not in str(record.get("category", "")).casefold():
        return False
    if source_type and source_type.casefold() != str(record.get("source_type", "")).casefold():
        return False
    return True


def local_library_query_match(record: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        [
            str(record.get("title", "")),
            str(record.get("source_url", "")),
            str(record.get("path", "")),
            str(record.get("category", "")),
            " ".join(str(item) for item in record.get("keywords", [])),
        ]
    ).casefold()
    return query.casefold() in haystack


def local_library_zero_trust_counters() -> dict[str, Any]:
    return {
        "filesystem_scans": 0,
        "source_note_writes": 0,
        "index_writes": 0,
        "sqlite_mutations": 0,
        "provider_call_count": 0,
        "media_download_count": 0,
        "credential_reads": 0,
        "external_api_syncs": 0,
    }


def zero_trust_counters() -> dict[str, Any]:
    return {
        "provider_call_count": 0,
        "media_download_count": 0,
        "credential_reads": 0,
        "source_note_writes": 0,
        "index_writes": 0,
        "queue_mutations": 0,
        "scheduler_installed": False,
    }


def source_detail_fallback_state(route_state: str) -> dict[str, Any]:
    policies = {
        "native_caption_available": {
            "fallback_required": False,
            "fallback_reason": "",
            "cc_available": True,
            "asr_gate_state": "closed_not_needed",
        },
        "source_ready": {
            "fallback_required": False,
            "fallback_reason": "",
            "cc_available": False,
            "asr_gate_state": "closed_until_route_decision",
        },
    }
    if route_state in policies:
        return policies[route_state]
    if route_state in {
        "no_transcript",
        "blocked_or_retry_later",
        "failed_recoverable",
        "failed_terminal",
        "route_failed",
    }:
        return {
            "fallback_required": True,
            "fallback_reason": route_state,
            "cc_available": False,
            "asr_gate_state": "closed_requires_separate_approval",
        }
    return {
        "fallback_required": False,
        "fallback_reason": "",
        "cc_available": False,
        "asr_gate_state": "closed_until_route_decision",
    }


def resume_blocked_gates() -> dict[str, bool]:
    return {
        "writeback_allowed": False,
        "provider_runtime_allowed": False,
        "media_runtime_allowed": False,
        "scheduler_installed": False,
        "credential_reads_allowed": False,
    }


def resume_approval_gates() -> dict[str, Any]:
    return {
        "writeback_allowed": False,
        "provider_runtime_allowed": False,
        "media_runtime_allowed": False,
        "scheduler_installed": False,
        "credential_reads_allowed": False,
        "auto_execute_after_resume": False,
        "writeback_requires_separate_approval": True,
    }


def resume_ui_restore_targets() -> list[str]:
    return [
        "left_rail_recent_job",
        "top_command_source_url",
        "source_inbox_selection",
        "transcript_evidence_review",
        "note_preview",
        "control_plane_recent_jobs",
        "bottom_status_resume_state",
    ]


def empty_resume_payload(
    workspace_root: str | Path,
    *,
    mode: str,
    reason: str,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    return {
        "ok": True,
        "read_only": True,
        "empty_state": True,
        "empty_reason": reason,
        "mode": mode,
        "resume_snapshot": {
            "workspace": {},
            "last_source": {},
            "last_job": {},
            "accepted_evidence": [],
            "note_draft": {},
            "failed_routes": [],
            "approval_gates": resume_approval_gates(),
            "rollback_refs": [],
        },
        "control_plane_summary": {
            "today_processed": 0,
            "pending_review": 0,
            "failed_route": 0,
            "blocked_note_previews": 0,
        },
        "ui_restore_targets": resume_ui_restore_targets(),
        "blocked_gates": resume_blocked_gates(),
        "trust_counters": zero_trust_counters(),
        "db_health": {
            "ok": False,
            "workspace_root": str(root),
            "db_path": str(root / DB_FILENAME),
            "database_exists": False,
            "schema_version": "",
            "read_only": True,
            **zero_trust_counters(),
        },
        "note_target_health": {
            "configured_count": 0,
            "preview_only_count": 0,
            "missing_path_count": 0,
            "targets": [],
        },
    }
