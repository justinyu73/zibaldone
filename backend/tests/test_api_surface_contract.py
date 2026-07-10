"""Characterization lock for the public FastAPI surface during router extraction."""

import unittest

import main as M


EXPECTED_API_SURFACE = frozenset(
    line.strip()
    for line in """
GET /api/app/capture-inbox
GET /api/app/config
GET /api/app/cost-breakdown
GET /api/app/cost-summary
GET /api/app/health
GET /api/app/inbox
GET /api/app/local-asr-model/status
GET /api/app/local-asr-runtime/readiness
GET /api/app/local-llm/status
GET /api/app/local-library/read-model
GET /api/app/meeting-audio
GET /api/app/meeting-note-job/{job_id}
GET /api/app/metrics
GET /api/app/model-options
GET /api/app/note-asset
GET /api/app/note-detail
GET /api/app/radar
GET /api/app/related-notes
GET /api/app/retained-artifacts
GET /api/app/retirement-candidates
GET /api/app/search
GET /api/app/secrets-status
GET /api/app/settings
GET /api/app/setup-readiness
GET /api/app/update-token
GET /api/app/value-library
GET /api/app/vault-folders
GET /api/health
GET /api/index
GET /api/model-policy
GET /api/provider-runtime/status
GET /api/translate-progress
POST /api/app/api-key
POST /api/app/api-key-clear
POST /api/app/api-key-test
POST /api/app/article-fetch
POST /api/app/article-save
POST /api/app/caption-probe
POST /api/app/capture-inbox-dismiss
POST /api/app/capture-pdf-convert
POST /api/app/estimate-text
POST /api/app/free-translate
POST /api/app/import-transcript
POST /api/app/inbox-review
POST /api/app/inbox-trash
POST /api/app/local-asr-model/download
POST /api/app/local-llm/builtin/install
POST /api/app/local-asr-report-only-probe
POST /api/app/meeting-audio-repair
POST /api/app/meeting-audio-ticket
POST /api/app/meeting-note
POST /api/app/meeting-note-job
POST /api/app/meeting-note-job/{job_id}/cancel
POST /api/app/meeting-note-job/{job_id}/retry
POST /api/app/meeting-note-save
POST /api/app/native-caption-api-probe
POST /api/app/note-links
POST /api/app/note-thought
POST /api/app/radar-dismiss
POST /api/app/radar-scan
POST /api/app/route
POST /api/app/settings
POST /api/app/storage-targets
POST /api/app/update-token
POST /api/app/value-signals
POST /api/app/vault-note-edit
POST /api/app/video-audio-asr
POST /api/app/ytdlp-subtitle-fallback-probe
POST /api/estimate
POST /api/estimate-source
POST /api/fetch
POST /api/production-extractor
POST /api/provider-runtime/asr
POST /api/provider-runtime/ocr
POST /api/save
POST /api/summarize
POST /api/translate
""".splitlines()
    if line.strip()
)


class ApiSurfaceContractTests(unittest.TestCase):
    def test_method_and_path_inventory_is_unchanged(self):
        actual = {
            f"{method} {route.path}"
            for route in M.app.routes
            if route.path.startswith("/api/")
            for method in (getattr(route, "methods", set()) or set())
            if method not in {"HEAD", "OPTIONS"}
        }

        self.assertSetEqual(actual, EXPECTED_API_SURFACE)
        self.assertEqual(len(actual), 77)


if __name__ == "__main__":
    unittest.main()
