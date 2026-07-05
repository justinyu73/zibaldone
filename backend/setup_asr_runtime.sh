#!/usr/bin/env bash
# Build the local whisper.cpp ASR runtime for the audio lane and write the
# runtime-lock.json that the backend readiness check verifies.
#
# Idempotent: re-running re-verifies the model sha1 and skips the 141MB
# download if it already matches. The binary/model live under YT_NOTE_ASR_ROOT
# (default ~/.config/yt-note-app) and are NOT committed to git.
#
# Requires: git cmake make cc g++ curl  (multilingual ggml-base model)
set -euo pipefail

ASR_ROOT="${YT_NOTE_ASR_ROOT:-$HOME/.config/yt-note-app}"
ROOT="$ASR_ROOT/tools/whisper.cpp"
SRC="$ASR_ROOT/tools/_whisper_src"
MODEL_NAME="ggml-base.bin"
OFFICIAL_SHA1="465707469ff3a37a2b9b8d8f89f2f99de7299dac"  # whisper.cpp models/README.md (base)

mkdir -p "$ROOT/bin" "$ROOT/models"

echo "[1/5] clone/refresh whisper.cpp"
if [ -d "$SRC/.git" ]; then git -C "$SRC" pull --ff-only || true; else
  rm -rf "$SRC"; git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$SRC"; fi

echo "[2/5] build whisper-cli"
cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF >/dev/null
cmake --build "$SRC/build" --config Release -j --target whisper-cli
cp "$(find "$SRC/build" -name whisper-cli -type f -perm -u+x | head -1)" "$ROOT/bin/whisper-cli"
HELP_EXIT=$("$ROOT/bin/whisper-cli" --help >/dev/null 2>&1; echo $?)

echo "[3/5] fetch model ($MODEL_NAME)"
MODEL="$ROOT/models/$MODEL_NAME"
if [ ! -f "$MODEL" ] || [ "$(sha1sum "$MODEL" | cut -d' ' -f1)" != "$OFFICIAL_SHA1" ]; then
  curl -fL --retry 3 -o "$MODEL" \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$MODEL_NAME"
fi

echo "[4/5] verify model against official sha1"
MODEL_SHA1=$(sha1sum "$MODEL" | cut -d' ' -f1)
[ "$MODEL_SHA1" = "$OFFICIAL_SHA1" ] || { echo "FATAL: model sha1 mismatch ($MODEL_SHA1)"; exit 1; }

echo "[5/5] write runtime-lock.json"
cat > "$ROOT/runtime-lock.json" <<EOF
{
  "runtime_name": "whisper.cpp",
  "runtime_version": "$(git -C "$SRC" rev-parse --short HEAD)",
  "build": {
    "build_ok": true,
    "binary_path": "tools/whisper.cpp/bin/whisper-cli",
    "binary_bytes": $(stat -c%s "$ROOT/bin/whisper-cli"),
    "binary_sha256": "$(sha256sum "$ROOT/bin/whisper-cli" | cut -d' ' -f1)",
    "help_exit_code": $HELP_EXIT
  },
  "model": {
    "path": "tools/whisper.cpp/models/$MODEL_NAME",
    "bytes": $(stat -c%s "$MODEL"),
    "sha1": "$MODEL_SHA1",
    "sha256": "$(sha256sum "$MODEL" | cut -d' ' -f1)",
    "official_sha1_expected": "$OFFICIAL_SHA1",
    "official_sha1_verified": true
  }
}
EOF
echo "DONE — runtime ready at $ROOT (model verified against official sha1)"
