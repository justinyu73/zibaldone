"""Host-header allowlist (DNS-rebinding guard)."""
import unittest

from main import host_header_allowed


class HostGuardTests(unittest.TestCase):
    def test_loopback_and_tauri_hosts_allowed(self):
        for host in ("127.0.0.1", "127.0.0.1:8766", "localhost:5173", "LOCALHOST",
                     "tauri.localhost", "ipc.localhost", ""):
            self.assertTrue(host_header_allowed(host), host)

    def test_foreign_hosts_rejected(self):
        for host in ("evil.example.com", "evil.example.com:8766", "192.168.1.10:8000",
                     "127.0.0.1.evil.com", "localhost.attacker.io"):
            self.assertFalse(host_header_allowed(host), host)


if __name__ == "__main__":
    unittest.main()
