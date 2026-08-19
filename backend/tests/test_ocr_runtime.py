"""ocr_runtime（OCR 引擎包首用下載）與 local_ocr（subprocess 客戶端）單元測試。"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import local_ocr
import ocr_runtime as OR


class ExpectedSha256Tests(unittest.TestCase):
    def test_parses_basename_from_sums_file(self):
        asset = "ocr-pack-linux-x64.zip"
        digest = hashlib.sha256(b"x").hexdigest()
        sums = f"{digest}  backend/dist/{asset}\n{'0'*64}  nsis/Zibaldone_0.9.0_x64-setup.exe\n"
        with mock.patch.object(OR, "_fetch_text", return_value=sums):
            self.assertEqual(OR._expected_sha256("https://x/sums.txt", asset), digest)

    def test_missing_asset_entry_raises(self):
        with mock.patch.object(OR, "_fetch_text", return_value="abc  other.zip\n"):
            with self.assertRaises(ValueError):
                OR._expected_sha256("https://x/sums.txt", "ocr-pack-linux-x64.zip")


class InstallWorkerTests(unittest.TestCase):
    def _make_pack_zip(self, dest: Path) -> bytes:
        payload = b"fake-binary"
        with zipfile.ZipFile(dest, "w") as zf:
            zf.writestr("ocr-pack/ocr-pack", payload)
        return dest.read_bytes()

    def test_install_happy_path(self):
        data = self._make_pack_zip
        with tempfile.TemporaryDirectory() as tmp:
            zip_bytes_holder = {}

            def fake_urlopen(request, timeout=None, context=None):
                url = request.full_url if hasattr(request, "full_url") else request
                if "ocr-pack" in url and "SHA256" not in url:
                    payload = zip_bytes_holder["bytes"]

                    class Resp:
                        headers = {"Content-Length": str(len(payload))}

                        def __enter__(self):
                            return self

                        def __exit__(self, *a):
                            return False

                        def read(self, n=-1):
                            if not hasattr(self, "_pos"):
                                self._pos = 0
                            chunk = payload[self._pos:self._pos + n] if n > 0 else payload
                            self._pos += len(chunk)
                            return chunk

                    return Resp()
                raise AssertionError(f"unexpected url {url}")

            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
                zip_path = Path(f.name)
            zip_bytes_holder["bytes"] = self._make_pack_zip(zip_path)
            digest = hashlib.sha256(zip_bytes_holder["bytes"]).hexdigest()

            exe = Path(tmp) / "ocr-pack" / "ocr-pack"
            with mock.patch.object(OR, "_root", lambda: Path(tmp)), \
                 mock.patch.object(OR, "pack_executable", lambda: str(exe) if exe.is_file() else None), \
                 mock.patch.object(OR, "_expected_sha256", return_value=digest), \
                 mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
                 mock.patch.object(OR.subprocess, "run") as run:
                run.return_value.returncode = 0
                OR._STATE.clear()
                OR._install_worker("linux-64")
            zip_path.unlink(missing_ok=True)
            self.assertEqual(OR._STATE.get("status"), "done", OR._STATE.get("error"))
            self.assertTrue(exe.is_file())
            self.assertTrue(os.stat(exe).st_mode & 0o111)

    def test_sha_mismatch_discards_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
                zip_path = Path(f.name)
            payload = self._make_pack_zip(zip_path)
            zip_path.unlink(missing_ok=True)

            class Resp:
                headers = {"Content-Length": str(len(payload))}

                def __init__(self):
                    self._pos = 0

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def read(self, n=-1):
                    chunk = payload[self._pos:self._pos + n]
                    self._pos += len(chunk)
                    return chunk

            with mock.patch.object(OR, "_root", lambda: Path(tmp)), \
                 mock.patch.object(OR, "_expected_sha256", return_value="0" * 64), \
                 mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: Resp()):
                OR._STATE.clear()
                OR._install_worker("linux-64")
            self.assertEqual(OR._STATE.get("status"), "error")
            self.assertIn("sha256", OR._STATE.get("error", ""))
            self.assertFalse((Path(tmp) / "ocr-pack.zip.part").exists())


class LocalOcrClientTests(unittest.TestCase):
    def test_pack_missing_raises_clean_guidance(self):
        with mock.patch("ocr_runtime.pack_executable", return_value=None):
            local_ocr._PROC = None
            with self.assertRaises(local_ocr.LocalOcrUnavailable) as ctx:
                local_ocr.ensure_ready()
            self.assertIn("下載", str(ctx.exception))

    def test_extract_text_roundtrip_via_fake_process(self):
        class FakeProc:
            def __init__(self):
                import io

                self.stdin = io.StringIO()
                self.stdout = io.StringIO(json.dumps({"ok": True, "ready": True}) + "\n" + json.dumps({"ok": True, "text": "第一行\n第二行"}) + "\n")

            def poll(self):
                return None

        with mock.patch("ocr_runtime.pack_executable", return_value="/x/ocr-pack"), \
             mock.patch.object(local_ocr.subprocess, "Popen", return_value=FakeProc()):
            local_ocr._PROC = None
            self.assertEqual(local_ocr.extract_text(b"png-bytes"), "第一行\n第二行")


if __name__ == "__main__":
    unittest.main()
