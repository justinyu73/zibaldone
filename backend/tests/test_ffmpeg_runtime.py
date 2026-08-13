"""ffmpeg/ffprobe 首次下載：封裝版 TLS context 回歸測試（CERTIFICATE_VERIFY_FAILED）。

_download_and_extract 的 urlopen 必須帶 radar._ssl_context()（certifi CA bundle）——
PyInstaller 打包版（尤其 macOS）找不到系統 CA store，不帶 context 時走 stdlib
預設路徑，下載會直接 CERTIFICATE_VERIFY_FAILED。這裡不連網，只用假 response
驗證 context 有被正確傳入、且既有下載/校驗流程沒被改動。
"""
import hashlib
import io
import os
import ssl
import tempfile
import unittest
import zipfile
from unittest import mock

import ffmpeg_runtime as FR
from radar import _ssl_context


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


class FfmpegDownloadTLSTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {"YT_NOTE_ASR_ROOT": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_download_passes_packaged_certifi_context(self):
        expected_ctx = _ssl_context()
        payload = b"fake-ffmpeg-binary"
        zip_bytes = _zip_bytes("ffmpeg", payload)
        sha256 = hashlib.sha256(zip_bytes).hexdigest()
        state = {"downloaded": 0, "total": 0}

        with mock.patch.object(FR.urllib.request, "urlopen", return_value=_FakeResponse(zip_bytes)) as opened:
            FR._download_and_extract("ffmpeg", "https://example.invalid/ffmpeg.zip", sha256, state)

        self.assertEqual(opened.call_count, 1)
        _, kwargs = opened.call_args
        # Same verified, certifi-backed singleton radar.py/free_translate.py already
        # use — never absent (stdlib default breaks in frozen macOS builds) and
        # never an unverified context.
        self.assertIs(kwargs.get("context"), expected_ctx)
        # Spell out what "verified" means so a future edit to radar._ssl_context()
        # that quietly weakens it (e.g. swaps in _create_unverified_context) fails
        # this test even if the `is expected_ctx` identity check still passes.
        self.assertIs(expected_ctx.check_hostname, True)
        self.assertEqual(expected_ctx.verify_mode, ssl.CERT_REQUIRED)

        installed = FR._installed_path("ffmpeg")
        self.assertTrue(installed.is_file())
        self.assertEqual(installed.read_bytes(), payload)
        self.assertTrue(os.access(installed, os.X_OK))
        self.assertEqual(state["downloaded"], len(zip_bytes))

    def test_sha256_mismatch_still_raises_and_discards_partial(self):
        zip_bytes = _zip_bytes("ffmpeg", b"fake-ffmpeg-binary")
        state = {"downloaded": 0, "total": 0}

        with mock.patch.object(FR.urllib.request, "urlopen", return_value=_FakeResponse(zip_bytes)):
            with self.assertRaises(ValueError):
                FR._download_and_extract("ffmpeg", "https://example.invalid/ffmpeg.zip", "0" * 64, state)

        self.assertFalse((FR._root() / "ffmpeg.zip.part").exists())
        self.assertFalse(FR._installed_path("ffmpeg").exists())


if __name__ == "__main__":
    unittest.main()
