#!/usr/bin/env bash
# Product quality gate for the Video Intake App backend.
# Stdlib unittest only — no provider/media/credential/network calls.
set -euo pipefail
cd "$(dirname "$0")"
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"
TEST_STATE_DIR="$(mktemp -d /tmp/yt-note-app-tests-XXXXXX)"
trap 'rm -rf "$TEST_STATE_DIR"' EXIT
export VIDEO_INTAKE_DISABLE_DOTENV=1
export YT_NOTE_APP_CONFIG_DIR="$TEST_STATE_DIR/config"
export YT_NOTE_ASR_ROOT="$TEST_STATE_DIR/asr"
"$PY" -m unittest discover -s tests -t . -v
