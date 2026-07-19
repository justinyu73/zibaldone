"""主機路徑正規化：Windows 打包版後端收 /mnt/<x>/ 要翻回 <X>:/，posix 反向."""
import unittest
from unittest import mock

import app_config
from app_config import normalize_host_path


class HostPathTest(unittest.TestCase):
    def test_posix_converts_windows_path(self):
        self.assertEqual(normalize_host_path("D:\\repos\\vault-notes"), "/mnt/d/repos/vault-notes")
        self.assertEqual(normalize_host_path("C:/Users/TestUser/Vault"), "/mnt/c/Users/TestUser/Vault")

    def test_posix_keeps_wsl_path(self):
        self.assertEqual(normalize_host_path("/mnt/d/repos/vault-notes"), "/mnt/d/repos/vault-notes")
        self.assertEqual(normalize_host_path("/home/user/notes"), "/home/user/notes")

    def test_nt_converts_wsl_path(self):
        with mock.patch.object(app_config.os, "name", "nt"):
            self.assertEqual(normalize_host_path("/mnt/d/repos/vault-notes"), "D:/repos/vault-notes")
            self.assertEqual(normalize_host_path("/mnt/c/Users/TestUser"), "C:/Users/TestUser")

    def test_nt_keeps_windows_path(self):
        with mock.patch.object(app_config.os, "name", "nt"):
            self.assertEqual(normalize_host_path("D:\\repos\\vault-notes"), "D:\\repos\\vault-notes")

    def test_empty_and_relative_untouched(self):
        self.assertEqual(normalize_host_path(""), "")
        self.assertEqual(normalize_host_path("  "), "")
        self.assertEqual(normalize_host_path("notes/sub"), "notes/sub")


if __name__ == "__main__":
    unittest.main()
