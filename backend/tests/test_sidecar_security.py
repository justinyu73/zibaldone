"""Local sidecar security guard tests."""
import os
import unittest
from unittest.mock import patch

import main
import sidecar_main


class SessionTokenGuardTests(unittest.TestCase):
    def test_no_configured_token_keeps_dev_mode_open(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YT_NOTE_APP_SESSION_TOKEN", None)
            self.assertFalse(main.session_token_required("/api/app/secrets-status", "GET"))
            self.assertTrue(main.session_token_valid(None))

    def test_configured_token_protects_api_except_health(self):
        with patch.dict(os.environ, {"YT_NOTE_APP_SESSION_TOKEN": "secret"}, clear=False):
            self.assertFalse(main.session_token_required("/api/health", "GET"))
            self.assertFalse(main.session_token_required("/api/app/health", "GET"))
            self.assertFalse(main.session_token_required("/api/app/secrets-status", "OPTIONS"))
            self.assertFalse(main.session_token_required("/api/app/meeting-audio", "GET"))
            self.assertTrue(main.session_token_required("/api/app/meeting-audio-ticket", "POST"))
            self.assertTrue(main.session_token_required("/api/app/secrets-status", "GET"))
            self.assertTrue(main.session_token_required("/api/app/api-key", "POST"))
            self.assertTrue(main.session_token_required("/api/save", "POST"))
            self.assertTrue(main.session_token_valid("secret"))
            self.assertFalse(main.session_token_valid(""))
            self.assertFalse(main.session_token_valid("wrong"))


class SidecarBindGuardTests(unittest.TestCase):
    def test_loopback_bind_allowed(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            with patch.dict(os.environ, {"VIDEO_INTAKE_FASTAPI_HOST": host}, clear=False):
                os.environ.pop("VIDEO_INTAKE_ALLOW_PUBLIC_BIND", None)
                self.assertEqual(sidecar_main._sidecar_host(), host)

    def test_public_bind_refused_without_explicit_override(self):
        with patch.dict(os.environ, {"VIDEO_INTAKE_FASTAPI_HOST": "0.0.0.0"}, clear=False):
            os.environ.pop("VIDEO_INTAKE_ALLOW_PUBLIC_BIND", None)
            with self.assertRaises(SystemExit):
                sidecar_main._sidecar_host()

    def test_public_bind_requires_explicit_override(self):
        with patch.dict(
            os.environ,
            {"VIDEO_INTAKE_FASTAPI_HOST": "0.0.0.0", "VIDEO_INTAKE_ALLOW_PUBLIC_BIND": "1"},
            clear=False,
        ):
            self.assertEqual(sidecar_main._sidecar_host(), "0.0.0.0")


if __name__ == "__main__":
    unittest.main()
