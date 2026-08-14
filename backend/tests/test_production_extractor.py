"""production_extractor.py regression tests (previously zero coverage).

stdlib unittest, no network/ffmpeg/OCR-model dependency — every external call
(yt-dlp metadata/download, ffprobe, ffmpeg frame grab, the local OCR engine)
is mocked. Two gaps from the win-asr-ocr-hardsub-recovery acceptance doc:

- B4: CAPS["storage_root"] / tempfile.mkdtemp(dir="/tmp") hardcoded a POSIX
  path that doesn't exist on stock Windows (FileNotFoundError before a single
  frame is sampled — reproduced and fixed this session).
- B3: local_ocr.extract_text() raising on one bad frame used to propagate as
  an unhandled exception out of the whole multi-frame pass, with no assertion
  that partial results survive or that tmp_root still gets cleaned up.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import production_extractor as PE


class StorageRootTests(unittest.TestCase):
    """B4 — Windows has no /tmp; storage_root must resolve per-platform and
    the directory must actually exist before mkdtemp(dir=...) is called."""

    def test_default_storage_root_tracks_platform_tempdir(self):
        # Regression: this must never again be a hardcoded "/tmp" literal —
        # it has to track whatever the platform's real temp dir resolves to
        # (tempfile.gettempdir() itself already handles TEMP/TMP/TMPDIR and
        # the Windows-vs-POSIX default).
        self.assertEqual(PE.CAPS["storage_root"], tempfile.gettempdir())

    def test_mkdtemp_on_a_missing_dir_raises_without_ensure_storage_root(self):
        # Documents the exact original failure mode: mkdtemp(dir=X) does NOT
        # create X, it only creates the random leaf under an *existing* X —
        # this is what raised FileNotFoundError on a stock Windows machine
        # (no C:\tmp) before this fix.
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "C_tmp_equivalent"
            with self.assertRaises(FileNotFoundError):
                tempfile.mkdtemp(dir=str(missing))

    def test_ensure_storage_root_creates_missing_dir_then_mkdtemp_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "C_tmp_equivalent" / "nested"
            self.assertFalse(missing.exists())
            with mock.patch.dict(PE.CAPS, {"storage_root": str(missing)}):
                # Exact call shape used by run_production_extractor().
                leaf = tempfile.mkdtemp(prefix="vaultwiki_yt_api_extract_", dir=PE._ensure_storage_root())
            self.assertTrue(missing.is_dir())
            self.assertTrue(Path(leaf).is_dir())


class LocalOcrSafetyTests(unittest.TestCase):
    """B3 (unit slice) — the per-frame catch itself: one bad frame's OCR
    exception must be caught, not propagated."""

    def test_successful_frame_returns_text_with_no_error(self):
        text, error = PE._run_local_ocr_safely(lambda data: "HARDSUBLINEONE", b"fake-png")
        self.assertEqual(text, "HARDSUBLINEONE")
        self.assertEqual(error, "")

    def test_engine_exception_is_caught_not_propagated(self):
        def boom(data):
            raise ValueError("corrupt frame, rapidocr choked")

        text, error = PE._run_local_ocr_safely(boom, b"bad-bytes")
        self.assertEqual(text, "")
        self.assertIn("corrupt frame", error)


def _fake_tooling_status():
    return {
        "ok": True,
        "tools": {
            "yt_dlp": {"available": True, "path": "python:yt_dlp", "version": "1.0"},
            "ffmpeg": {"available": True, "path": "/fake/ffmpeg", "version": "fake"},
            "ffprobe": {"available": True, "path": "/fake/ffprobe", "version": "fake"},
        },
        "missing": [],
    }


def _fake_run_command(command, timeout=90):
    # The frame-grab call's last arg is always the destination frame path
    # (production_extractor.py's ffmpeg command list). Write distinct bytes
    # per frame so each gets a different sha256 (otherwise they'd collide on
    # the provider_cache dedup path and only one real OCR call would fire).
    dest = Path(command[-1])
    dest.write_bytes(f"fake-frame:{dest.stem}".encode())
    return ""


class OcrPartialFailureIntegrationTests(unittest.TestCase):
    """B3 (end-to-end) — a mid-pass OCR failure must not blow up the whole
    request: it should surface as a per-frame error while the run still
    returns ok=True with the other frame's text, and tmp_root must still be
    cleaned up (the pre-existing try/finally, verified not to have regressed)."""

    def setUp(self):
        self.video_id = "fakeVideoId1"
        patches = [
            mock.patch.object(PE, "tooling_status", side_effect=_fake_tooling_status),
            mock.patch.object(PE, "_metadata", return_value={
                "id": self.video_id, "title_present": True, "duration_seconds": 10.0,
                "extractor": "youtube", "availability": "public",
            }),
            mock.patch.object(PE, "_download_lowres_video", return_value="/fake/video.mp4"),
            mock.patch.object(PE, "_probe", return_value={
                "probe_status": "pass", "codec_name": "h264", "width": 640, "height": 360,
                "r_frame_rate": "25/1", "stream_duration_seconds": 10.0,
            }),
            mock.patch.object(PE, "_run_command", side_effect=_fake_run_command),
            mock.patch("local_ocr.ensure_ready", return_value=None),
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_one_bad_frame_leaves_partial_result_and_cleans_up(self):
        calls = {"n": 0}

        def fake_extract_text(data: bytes) -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("corrupt frame, rapidocr choked")
            return "SECONDFRAMETEXT"

        with mock.patch("local_ocr.extract_text", side_effect=fake_extract_text):
            result = PE.run_production_extractor(
                url=self.video_id,
                mode="real",
                sample_count=2,
                user_authorized_media=True,
                allow_provider_ocr=True,
                confirm_report_only=True,
            )

        # The whole request still succeeds — one bad frame does not 500 it.
        self.assertTrue(result["ok"])
        self.assertEqual(result["sampled_frame_count"], 2)
        self.assertEqual(calls["n"], 2)  # both frames actually ran OCR (no accidental sha256 collision)

        evidence = result["provider_evidence"]
        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0]["status"], "local_frame_failed")
        self.assertIn("corrupt frame", evidence[0]["ocr_error"])
        self.assertEqual(evidence[0]["text"], "")
        self.assertEqual(evidence[1]["status"], "local_completed")
        self.assertNotIn("ocr_error", evidence[1])
        self.assertEqual(evidence[1]["text"], "SECONDFRAMETEXT")

        # Partial result: the failed frame contributes nothing, the good one does.
        self.assertIn("SECONDFRAMETEXT", result["ocr_text"])

        # tmp_root cleanup still holds (pre-existing try/finally, not regressed).
        self.assertTrue(result["cleanup_verified"])


if __name__ == "__main__":
    unittest.main()
