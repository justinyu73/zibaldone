"""whisper_runtime：預建 whisper.cpp 一鍵下載的單元測試（不下真網路、不跑真二進位）。"""
from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import whisper_runtime as WR


def _fake_download(payload: bytes, digest: str = "ok"):
    def _write(url: str, dest, digest_name: str) -> str:
        Path(dest).write_bytes(payload)
        return digest

    return _write


class WantedMemberTests(unittest.TestCase):
    def test_keeps_cli_and_shared_libs_only(self):
        with mock.patch.object(WR, "_EXE", ""):
            self.assertEqual(WR._wanted_member("pkg/whisper-cli"), "whisper-cli")
            self.assertEqual(WR._wanted_member("Release/whisper-cli.exe"), "")
        with mock.patch.object(WR, "_EXE", ".exe"):
            self.assertEqual(WR._wanted_member("Release/whisper-cli.exe"), "whisper-cli.exe")
            self.assertEqual(WR._wanted_member("pkg/whisper-cli"), "")
        self.assertEqual(WR._wanted_member("Release/ggml.dll"), "ggml.dll")
        self.assertEqual(WR._wanted_member("pkg/libwhisper.so.1.9.2"), "libwhisper.so.1.9.2")
        self.assertEqual(WR._wanted_member("pkg/whisper-server"), "")
        self.assertEqual(WR._wanted_member("Release/test-vad.exe"), "")
        self.assertEqual(WR._wanted_member("pkg/LICENSE"), "")


class InstallBinaryTests(unittest.TestCase):
    def _zip_bytes(self, names: list[str]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name in names:
                z.writestr(name, b"x")
        return buf.getvalue()

    def test_zip_extracts_cli_and_dlls(self):
        payload = self._zip_bytes(["Release/whisper-cli.exe", "Release/ggml.dll", "Release/stream.exe"])
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(WR, "_EXE", ".exe"), \
                 mock.patch.object(WR, "_bin_dir", lambda: Path(tmp)), \
                 mock.patch.object(WR, "_binary_path", lambda: Path(tmp) / "whisper-cli.exe"), \
                 mock.patch.object(WR, "_download_file", side_effect=_fake_download(payload)):
                WR._install_binary({"url": "u", "sha256": "ok", "archive": "zip"})
            self.assertTrue((Path(tmp) / "whisper-cli.exe").is_file())
            self.assertTrue((Path(tmp) / "ggml.dll").is_file())
            self.assertFalse((Path(tmp) / "stream.exe").exists())

    def test_targz_extracts_cli_and_shared_libs(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            for name in ["pkg/whisper-cli", "pkg/libwhisper.so", "pkg/whisper-server"]:
                data = b"x"
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
        payload = buf.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(WR, "_bin_dir", lambda: Path(tmp)), \
                 mock.patch.object(WR, "_binary_path", lambda: Path(tmp) / "whisper-cli"), \
                 mock.patch.object(WR, "_download_file", side_effect=_fake_download(payload)):
                WR._install_binary({"url": "u", "sha256": "ok", "archive": "tar.gz"})
            self.assertTrue((Path(tmp) / "whisper-cli").is_file())
            self.assertTrue((Path(tmp) / "libwhisper.so").is_file())
            self.assertFalse((Path(tmp) / "whisper-server").exists())

    def test_sha_mismatch_discards_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(WR, "_bin_dir", lambda: Path(tmp)), \
                 mock.patch.object(WR, "_download_file", return_value="bad"):
                with self.assertRaises(ValueError):
                    WR._install_binary({"url": "u", "sha256": "expected", "archive": "zip"})

    def test_missing_cli_in_archive_raises(self):
        payload = self._zip_bytes(["Release/ggml.dll"])
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(WR, "_EXE", ".exe"), \
                 mock.patch.object(WR, "_bin_dir", lambda: Path(tmp)), \
                 mock.patch.object(WR, "_binary_path", lambda: Path(tmp) / "whisper-cli.exe"), \
                 mock.patch.object(WR, "_download_file", side_effect=_fake_download(payload)):
                with self.assertRaises(ValueError):
                    WR._install_binary({"url": "u", "sha256": "ok", "archive": "zip"})


class ModelInstallTests(unittest.TestCase):
    def test_sha1_mismatch_discards_part_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "ggml-base.bin"
            with mock.patch.object(WR, "_model_path", lambda: dest), \
                 mock.patch.object(WR, "_download_file", return_value="deadbeef"):
                with self.assertRaises(ValueError):
                    WR._install_model()
            self.assertFalse(dest.exists())
            self.assertFalse(dest.with_suffix(".bin.part").exists())


class LockWriteTests(unittest.TestCase):
    def test_written_lock_passes_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "tools/whisper.cpp/bin/whisper-cli"
            model = root / "tools/whisper.cpp/models/ggml-base.bin"
            binary.parent.mkdir(parents=True)
            model.parent.mkdir(parents=True)
            binary.write_bytes(b"bin")
            model.write_bytes(b"model")
            with mock.patch.dict(os.environ, {"YT_NOTE_ASR_ROOT": tmp}), \
                 mock.patch.object(WR, "_binary_path", lambda: binary), \
                 mock.patch.object(WR, "_model_path", lambda: model), \
                 mock.patch.object(WR, "_lock_path", lambda: root / "tools/whisper.cpp/runtime-lock.json"), \
                 mock.patch.object(WR.subprocess, "run") as run:
                run.return_value.returncode = 0
                WR._write_lock()
                from services.readiness import _local_asr_runtime_readiness

                readiness = _local_asr_runtime_readiness()
            lock = json.loads((root / "tools/whisper.cpp/runtime-lock.json").read_text())
            self.assertTrue(lock["build"]["build_ok"])
            self.assertTrue(lock["model"]["official_sha1_verified"])
            self.assertEqual(lock["model"]["sha1"], hashlib.sha1(b"model").hexdigest())
            self.assertTrue(readiness["runtime_ready"])


class PlatformGateTests(unittest.TestCase):
    def test_unsupported_platform_raises(self):
        with mock.patch.object(WR, "_os_key", return_value="macos"):
            with self.assertRaises(ValueError):
                WR.start_install()
        self.assertNotEqual(WR._DOWNLOAD.get("status"), "downloading")


if __name__ == "__main__":
    unittest.main()
