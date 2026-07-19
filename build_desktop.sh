#!/usr/bin/env bash
# Build the installable desktop app (block #8c).
# Chains the standalone sidecar build (#8b) and the Tauri bundle, so the
# resulting .deb is self-contained (ships the FastAPI sidecar binary; no dev
# server / source / venv needed at install time).
#
# Linux prerequisites (verified present on this WSL): webkit2gtk-4.1, gtk+-3.0,
# libsoup-3.0, librsvg-2.0; pyinstaller in backend/.venv; tauri-cli.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "[1/2] building standalone sidecar (#8b)…"
"$HERE/backend/build_sidecar.sh"

echo "[2/2] building Tauri desktop bundle (#8c)…"
cd "$HERE/frontend"
# deb + AppImage both verified on this WSL (AppImage needs APPIMAGE_EXTRACT_AND_RUN).
NO_STRIP=1 APPIMAGE_EXTRACT_AND_RUN=1 npx tauri build --bundles deb,appimage

echo "done. bundles at: frontend/src-tauri/target/release/bundle/{deb,appimage}/"
