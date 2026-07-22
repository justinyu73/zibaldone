#!/usr/bin/env bash
# Start the exact sidecar resource that will ship in a desktop bundle, then prove
# both a public health request and a session-protected API request. The caller
# passes an OS-native PyInstaller executable path after `tauri build`.
set -euo pipefail

SIDECAR_PATH="${1:?usage: smoke_bundled_sidecar.sh <sidecar-path> [port]}"
SIDECAR_PORT="${2:-18766}"
SMOKE_TMP="$(mktemp -d)"
SMOKE_LOG="$SMOKE_TMP/sidecar.log"
SMOKE_PID=""

cleanup() {
  if [[ -n "$SMOKE_PID" ]]; then
    kill "$SMOKE_PID" 2>/dev/null || true
    wait "$SMOKE_PID" 2>/dev/null || true
  fi
  rm -rf "$SMOKE_TMP"
}
trap cleanup EXIT

test -f "$SIDECAR_PATH"
echo "[sidecar-smoke] executable: $SIDECAR_PATH"

VIDEO_INTAKE_FASTAPI_PORT="$SIDECAR_PORT" \
YT_NOTE_APP_SESSION_TOKEN="release-sidecar-smoke-token" \
YT_NOTE_APP_CONFIG_DIR="$SMOKE_TMP/config" \
YT_NOTE_ASR_ROOT="$SMOKE_TMP/asr" \
"$SIDECAR_PATH" >"$SMOKE_LOG" 2>&1 &
SMOKE_PID="$!"

BASE_URL="http://127.0.0.1:$SIDECAR_PORT/api"
SMOKE_READY=0
for _ in $(seq 1 40); do
  if curl --fail --silent "$BASE_URL/health" >"$SMOKE_TMP/health.json" 2>/dev/null; then
    SMOKE_READY=1
    break
  fi
  if ! kill -0 "$SMOKE_PID" 2>/dev/null; then
    cat "$SMOKE_LOG"
    exit 1
  fi
  sleep 0.25
done

if [[ "$SMOKE_READY" -ne 1 ]]; then
  cat "$SMOKE_LOG"
  exit 1
fi
test -s "$SMOKE_TMP/health.json"
grep -q '"model_policy"' "$SMOKE_TMP/health.json"
curl --fail --silent --show-error \
  -H 'X-YT-Note-Token: release-sidecar-smoke-token' \
  "$BASE_URL/app/cost-summary" >"$SMOKE_TMP/cost-summary.json"
grep -q '"daily_cap_usd"' "$SMOKE_TMP/cost-summary.json"
echo "[sidecar-smoke] PASS health + protected cost summary"
