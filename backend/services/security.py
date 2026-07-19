"""Session-token config shared by main's security middleware and the media ticket gate."""
from __future__ import annotations

import os


def configured_session_token() -> str:
    return os.getenv("YT_NOTE_APP_SESSION_TOKEN", "").strip()
