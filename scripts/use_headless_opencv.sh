#!/usr/bin/env bash
# Slim the OCR payload: RapidOCR only decodes and transforms still images, so
# the full opencv-python build (Qt GUI libs on Linux) is dead weight. Swap it
# for the headless build at the SAME version — rapidocr's cv2 API usage is
# fully covered. Used by scripts/build_ocr_pack.sh for the downloadable OCR
# pack (no longer needed for the main sidecar, which carries no OCR stack).
#
# pip metadata will report rapidocr's opencv-python dependency as unsatisfied
# afterwards; that is expected — cv2 is present, just from headless.
#
# Keep the pin in sync with the opencv-python version rapidocr resolves to.
set -euo pipefail

HEADLESS_VERSION="4.11.0.86"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -x "$ROOT/backend/.venv/bin/pip" ]]; then
  PIP=("$ROOT/backend/.venv/bin/pip")
elif [[ -x "$ROOT/backend/.venv/Scripts/pip.exe" ]]; then
  PIP=("$ROOT/backend/.venv/Scripts/pip.exe")
else
  PIP=(pip)
fi

"${PIP[@]}" uninstall -y opencv-python || true
# --force-reinstall: the full package's uninstall above deletes the shared
# cv2/ file tree; if pip considers headless "already satisfied" it would
# otherwise skip the install and leave cv2 missing entirely.
"${PIP[@]}" install --force-reinstall --no-deps "opencv-python-headless==${HEADLESS_VERSION}"
