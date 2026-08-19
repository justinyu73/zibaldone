#!/usr/bin/env bash
# Slim the packaged sidecar: RapidOCR only decodes and transforms still
# images, so the full opencv-python build (Qt GUI libs + libav video I/O,
# ~90MB raw / ~20MB installer) is dead weight. Swap it for the headless
# build at the SAME version — rapidocr's cv2 API usage is fully covered.
#
# Run after `pip install -r backend/requirements.txt` (which pulls in the
# full opencv-python as a rapidocr-onnxruntime dependency). pip metadata
# will report the dependency as unsatisfied afterwards; that is expected —
# cv2 is present, just from the headless distribution.
#
# Keep the pin in sync with the opencv-python version rapidocr resolves to.
set -euo pipefail

HEADLESS_VERSION="4.11.0.86"

PIP=(pip)
if [[ -x backend/.venv/bin/pip ]]; then
  PIP=(backend/.venv/bin/pip)
fi

"${PIP[@]}" uninstall -y opencv-python || true
"${PIP[@]}" install "opencv-python-headless==${HEADLESS_VERSION}"
