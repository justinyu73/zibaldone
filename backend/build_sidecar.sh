#!/usr/bin/env bash
# Build the standalone FastAPI sidecar binary (block #8b) and place it for Tauri.
# The binary is a regenerable build artifact (gitignored); run this before a
# tauri build. Needs pyinstaller in the backend venv (pip install pyinstaller).
set -euo pipefail
cd "$(dirname "$0")"
TRIPLE="$(rustc -vV | sed -n 's/host: //p')"
rm -rf build dist ./*.spec
.venv/bin/pyinstaller --onefile --name video-intake-fastapi-sidecar \
  --add-data "enabled_models.json:." \
  --collect-submodules uvicorn --collect-submodules anyio \
  --collect-submodules anthropic --collect-submodules google.genai \
  --copy-metadata anthropic --copy-metadata google-genai \
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on \
  sidecar_main.py
DEST="../frontend/src-tauri/binaries/video-intake-fastapi-sidecar-${TRIPLE}"
cp dist/video-intake-fastapi-sidecar "$DEST"
chmod +x "$DEST"
echo "placed standalone sidecar: $DEST"
