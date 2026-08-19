#!/usr/bin/env bash
# Build the downloadable OCR pack (RapidOCR + OpenCV + onnxruntime as a
# standalone onedir) and zip it as backend/dist/ocr-pack-<os-key>.zip for
# release upload. Kept out of the main sidecar on purpose — see ocr_runtime.py.
#
# The pack installs its own dependencies (rapidocr + headless OpenCV at the
# same version, reusing scripts/use_headless_opencv.sh's pin), independent of
# backend/requirements.txt, which no longer carries the OCR stack.
set -euo pipefail
cd "$(dirname "$0")/../backend"

RAPIDOCR_VERSION="1.3.24"

if [[ -x .venv/bin/pip ]]; then
  PIP=(.venv/bin/pip)
  PYI=(.venv/bin/pyinstaller)
  PY=(.venv/bin/python)
elif [[ -x .venv/Scripts/pip.exe ]]; then
  PIP=(.venv/Scripts/pip.exe)
  PYI=(.venv/Scripts/pyinstaller.exe)
  PY=(.venv/Scripts/python.exe)
else
  PIP=(pip)
  PYI=(pyinstaller)
  PY=(python)
fi

# rapidocr pulls full opencv-python; swap to headless so the pack ships no Qt.
"${PIP[@]}" install "rapidocr-onnxruntime==${RAPIDOCR_VERSION}"
bash ../scripts/use_headless_opencv.sh

case "${OSTYPE:-}" in
  msys*|cygwin*|win32*) OS_KEY="windows-x64" ;;
  darwin*)              OS_KEY="macos-arm64" ;;
  *)                    OS_KEY="linux-x64" ;;
esac

rm -rf build/ocr-pack dist/ocr-pack "dist/ocr-pack-${OS_KEY}.zip" ocr-pack.spec
"${PYI[@]}" --onedir --name ocr-pack \
  --workpath build/ocr-pack \
  --collect-submodules rapidocr_onnxruntime --collect-data rapidocr_onnxruntime \
  --collect-data onnxruntime --collect-binaries onnxruntime \
  ocr_pack_main.py

"${PY[@]}" - "$OS_KEY" <<'PY'
import shutil, sys
shutil.make_archive(f"dist/ocr-pack-{sys.argv[1]}", "zip", "dist", "ocr-pack")
print("packed:", f"dist/ocr-pack-{sys.argv[1]}.zip")
PY
sha256sum "dist/ocr-pack-${OS_KEY}.zip" 2>/dev/null || shasum -a 256 "dist/ocr-pack-${OS_KEY}.zip"
