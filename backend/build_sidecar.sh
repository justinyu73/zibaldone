#!/usr/bin/env bash
# Build both Tauri sidecar modes (block #8b):
# - release: PyInstaller onedir resource tree;
# - dev: target-suffixed PyInstaller onefile externalBin.
# Both are regenerable build artifacts (gitignored). Run this before tauri dev
# or tauri build. Needs pyinstaller in the backend venv.
set -euo pipefail
cd "$(dirname "$0")"

if [[ -x .venv/bin/pyinstaller ]]; then
  PYI=(.venv/bin/pyinstaller)
elif [[ -x .venv/Scripts/pyinstaller.exe ]]; then
  PYI=(.venv/Scripts/pyinstaller.exe)
else
  PYI=(pyinstaller)
fi
TRIPLE="$(rustc -vV | sed -n 's/host: //p')"
case "${OSTYPE:-}" in
  msys*|cygwin*|win32*) DATA_SEP=';'; DEV_EXT='.exe' ;;
  *) DATA_SEP=':'; DEV_EXT='' ;;
esac
COMMON_ARGS=(
  --add-data "enabled_models.json${DATA_SEP}."
  --collect-submodules uvicorn --collect-submodules anyio
  --collect-data trafilatura --collect-data justext --collect-data tld --collect-data certifi
  --collect-submodules anthropic --collect-submodules google.genai
  --collect-submodules yt_dlp --copy-metadata yt-dlp
  --copy-metadata anthropic --copy-metadata google-genai
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto
  --hidden-import uvicorn.protocols.http.auto
  --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on
)

rm -rf build dist ./*.spec

"${PYI[@]}" --onedir --name video-intake-fastapi-sidecar \
  "${COMMON_ARGS[@]}" sidecar_main.py
rm -rf ../frontend/src-tauri/binaries/video-intake-fastapi-sidecar
mkdir -p ../frontend/src-tauri/binaries
cp -R dist/video-intake-fastapi-sidecar \
  ../frontend/src-tauri/binaries/video-intake-fastapi-sidecar

# Tauri's debug shell plugin resolves this exact target-suffixed filename from
# bundle.externalBin. It is deliberately separate from the release resource:
# dev keeps the externalBin contract, release keeps the faster onedir layout.
"${PYI[@]}" --onefile --name video-intake-fastapi-sidecar-dev \
  "${COMMON_ARGS[@]}" sidecar_main.py
DEV_DEST="../frontend/src-tauri/binaries/video-intake-fastapi-sidecar-dev-${TRIPLE}${DEV_EXT}"
cp "dist/video-intake-fastapi-sidecar-dev${DEV_EXT}" "$DEV_DEST"
chmod +x "$DEV_DEST" 2>/dev/null || true
echo "placed onedir sidecar: ../frontend/src-tauri/binaries/video-intake-fastapi-sidecar"
echo "placed dev externalBin: $DEV_DEST"
