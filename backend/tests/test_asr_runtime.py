"""asr_runtime.py — whisper.cpp precompiled runtime first-run download tests.

stdlib unittest, no network — same .part/sha256/atomic-install mocking shape
as test_ffmpeg_runtime.py (packaged-app TLS context regression included: same
bug class the ffmpeg download hit and was fixed for in eccb550). Also proves
a full successful install produces a runtime-lock.json that
services.readiness._local_asr_runtime_readiness() actually accepts, without
needing to change that readiness contract.
"""
import hashlib
import io
import os
import ssl
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import asr_runtime as AR
from radar import _ssl_context
from services.readiness import _local_asr_runtime_readiness


def _zip_bytes(member_name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member_name, content)
    return buf.getvalue()


class _FakeResponse:
    """Minimal urlopen() context-manager stand-in — no socket, no network."""

    def __init__(self, payload: bytes):
        self._buf = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class AsrRuntimeInstallTests(unittest.TestCase):
    def setUp(self):
        AR._STATE.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {"YT_NOTE_ASR_ROOT": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        # Force a supported OS key regardless of the actual test host.
        self.os_key_patch = mock.patch.object(AR, "_os_key", return_value="linux-64")
        self.os_key_patch.start()
        self.addCleanup(self.os_key_patch.stop)

    def test_binary_download_passes_packaged_certifi_context(self):
        expected_ctx = _ssl_context()
        payload = _zip_bytes("whisper-cli", b"#!/bin/sh\necho fake-whisper-cli\n")
        sha256 = hashlib.sha256(payload).hexdigest()
        state = {"downloaded": 0, "total": 0}

        with mock.patch.dict(AR._REGISTRY, {"linux-64": {"url": "https://example.invalid/whisper.zip", "sha256": sha256}}):
            with mock.patch.object(AR.urllib.request, "urlopen", return_value=_FakeResponse(payload)) as opened:
                with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout="usage: whisper-cli", stderr="")):
                    build = AR._install_binary("linux-64", state)

        self.assertEqual(opened.call_count, 1)
        _, kwargs = opened.call_args
        # Same verified, certifi-backed singleton ffmpeg_runtime.py already
        # uses (test_ffmpeg_runtime.py pins the same shape) — never absent
        # (stdlib default breaks in frozen builds without a system CA store).
        self.assertIs(kwargs.get("context"), expected_ctx)
        self.assertIs(expected_ctx.check_hostname, True)
        self.assertEqual(expected_ctx.verify_mode, ssl.CERT_REQUIRED)

        self.assertTrue(build["build_ok"])
        self.assertEqual(build["help_exit_code"], 0)
        installed = Path(build["binary_path"])
        self.assertTrue(installed.is_file())
        self.assertEqual(installed.name, "whisper-cli")
        self.assertEqual(build["binary_bytes"], installed.stat().st_size)

    def test_binary_sha256_mismatch_discards_partial_and_raises(self):
        payload = _zip_bytes("whisper-cli", b"fake binary, wrong checksum")
        state = {"downloaded": 0, "total": 0}

        with mock.patch.dict(AR._REGISTRY, {"linux-64": {"url": "https://example.invalid/whisper.zip", "sha256": "0" * 64}}):
            with mock.patch.object(AR.urllib.request, "urlopen", return_value=_FakeResponse(payload)):
                with self.assertRaises(ValueError):
                    AR._install_binary("linux-64", state)

        root = AR._root()
        self.assertFalse((root / "archive.zip").exists())
        self.assertFalse((root / "archive.zip.part").exists())
        self.assertFalse(AR._bin_dir().exists())

    def test_binary_that_fails_to_run_is_not_reported_installed(self):
        # An extracted binary that can't even run --help (e.g. missing a
        # sibling DLL/.so) must not be reported as a successful install.
        payload = _zip_bytes("whisper-cli", b"not actually runnable")
        sha256 = hashlib.sha256(payload).hexdigest()
        state = {"downloaded": 0, "total": 0}

        with mock.patch.dict(AR._REGISTRY, {"linux-64": {"url": "https://example.invalid/whisper.zip", "sha256": sha256}}):
            with mock.patch.object(AR.urllib.request, "urlopen", return_value=_FakeResponse(payload)):
                with mock.patch("subprocess.run", return_value=mock.Mock(returncode=127, stdout="", stderr="error while loading shared libraries")):
                    with self.assertRaises(ValueError):
                        AR._install_binary("linux-64", state)

    def test_full_install_writes_readiness_compatible_lock_file(self):
        binary_payload = _zip_bytes("whisper-cli", b"#!/bin/sh\necho fake-whisper-cli\n")
        binary_sha256 = hashlib.sha256(binary_payload).hexdigest()
        model_payload = b"fake-ggml-base-bin-content"
        model_sha1 = hashlib.sha1(model_payload).hexdigest()
        responses = iter([_FakeResponse(binary_payload), _FakeResponse(model_payload)])

        with mock.patch.dict(AR._REGISTRY, {"linux-64": {"url": "https://example.invalid/whisper.zip", "sha256": binary_sha256}}):
            with mock.patch.object(AR, "_MODEL_SHA1", model_sha1):
                with mock.patch.object(AR.urllib.request, "urlopen", side_effect=lambda *a, **k: next(responses)):
                    with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout="usage: whisper-cli", stderr="")):
                        AR._install_worker("linux-64")

        self.assertEqual(AR._STATE.get("status"), "done", AR._STATE.get("error"))
        self.assertTrue(AR._lock_path().is_file())

        # This is the exact contract services.readiness._local_asr_runtime_readiness()
        # already reads — proving the new download path satisfies it without
        # any change to readiness.py or its callers.
        readiness = _local_asr_runtime_readiness()
        self.assertTrue(readiness["binary_ready"])
        self.assertTrue(readiness["model_ready"])
        self.assertTrue(readiness["runtime_ready"])

        status = AR.status()
        self.assertTrue(status["ready"])


if __name__ == "__main__":
    unittest.main()
