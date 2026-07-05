"""Provider runtime ASR/OCR safety-contract tests (block #9, in-band).

The ASR/OCR runtime is the highest-risk module (provider + media + credential).
These tests lock its safety boundaries WITHOUT any real provider call, media
download, or credential use: base64 decode limits, the refuse-without-key /
disabled-task gate, the read-only runtime status, and the dry-run report shape.
A real transcription needs operator-supplied media + a live key + spend — a
separate, deeper gate not exercised here.
"""
import base64
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import provider_runtime as PR  # noqa: E402


class DecodeMediaTests(unittest.TestCase):
    def test_valid_base64_decodes(self):
        b64 = base64.b64encode(b"hello").decode()
        self.assertEqual(PR.decode_media(b64, 100), b"hello")

    def test_strips_data_uri_prefix(self):
        b64 = base64.b64encode(b"frame-bytes").decode()
        self.assertEqual(PR.decode_media(f"data:image/png;base64,{b64}", 100), b"frame-bytes")

    def test_empty_raises_400(self):
        with self.assertRaises(PR.ProviderRuntimeError) as ctx:
            PR.decode_media("   ", 100)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_base64_raises_400(self):
        with self.assertRaises(PR.ProviderRuntimeError) as ctx:
            PR.decode_media("not!valid!base64!", 100)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_over_limit_raises_413(self):
        b64 = base64.b64encode(b"x" * 50).decode()
        with self.assertRaises(PR.ProviderRuntimeError) as ctx:
            PR.decode_media(b64, 10)
        self.assertEqual(ctx.exception.status_code, 413)


class RequireRealRuntimeTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("OPENAI_API_KEY")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = self._saved

    def test_disabled_task_raises_403(self):
        os.environ["OPENAI_API_KEY"] = "test-key"
        with self.assertRaises(PR.ProviderRuntimeError) as ctx:
            PR._require_real_runtime("not_a_real_task")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_enabled_task_without_key_raises_400(self):
        os.environ.pop("OPENAI_API_KEY", None)
        with self.assertRaises(PR.ProviderRuntimeError) as ctx:
            PR._require_real_runtime("asr")
        self.assertEqual(ctx.exception.status_code, 400)


class RuntimeStatusTests(unittest.TestCase):
    def test_status_exposes_blocked_scope_and_enabled_tasks(self):
        status = PR.runtime_status()
        self.assertTrue(status["ok"])
        self.assertIn("platform_media_download", status["blocked_scope"])
        self.assertIn("durable_source_note_write", status["blocked_scope"])
        self.assertIn("background_scheduler", status["blocked_scope"])
        # asr + ocr_visual are enabled in enabled_models.json
        self.assertIn("asr", status["enabled_runtime_tasks"])
        self.assertIn("ocr_visual", status["enabled_runtime_tasks"])


class DryRunReportTests(unittest.TestCase):
    def test_dry_run_report_records_zero_spend_and_blocked_scope(self):
        report = PR._dry_run_report("asr", "asr", "gpt-4o-transcribe", "audio.mp3", "audio/mpeg", 1234)
        self.assertEqual(report["execution_mode"], "dry_run")
        self.assertEqual(report["provider_call_count"], 0)
        self.assertEqual(report["credential_reads"], 0)
        self.assertEqual(report["durable_writes"], 0)
        self.assertIn("platform_media_download", report["blocked_scope"])
        self.assertEqual(report["input"]["surface"], "operator_supplied_media_base64")


if __name__ == "__main__":
    unittest.main()
