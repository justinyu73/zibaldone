#!/usr/bin/env bash
# E2E backend launcher: local dev uses .venv, CI uses system python.
# Dotenv is disabled so e2e never inherits a developer's real vault/key config.
set -euo pipefail
cd "$(dirname "$0")"
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
export VIDEO_INTAKE_DISABLE_DOTENV=1
# Hermetic app-state dir: fingerprints (radar/capture) and settings must not
# touch the developer's real ~/.config/yt-note-app.
export YT_NOTE_APP_CONFIG_DIR="${YT_NOTE_APP_CONFIG_DIR:-$(mktemp -d /tmp/vi-e2e-cfg-XXXXXX)}"
export YT_NOTE_ASR_ROOT="${YT_NOTE_ASR_ROOT:-$YT_NOTE_APP_CONFIG_DIR/asr}"
exec "$PY" -m uvicorn main:app --host 127.0.0.1 --port "${VIDEO_INTAKE_FASTAPI_PORT:-8000}"
