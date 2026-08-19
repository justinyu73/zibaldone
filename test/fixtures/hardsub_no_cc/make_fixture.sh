#!/usr/bin/env bash
# Generate a small, deterministic, offline "hardsub, no CC" video fixture for
# the OCR hardsub-recovery lane (backend/local_ocr.py, backend/production_extractor.py).
#
# Why synthesized instead of a downloaded real YouTube video (see also
# test/fixtures/hardsub_no_cc/README.md):
#   - reproducible/offline: no network at test time, no dependency on a
#     third-party video staying up, public, and unchanged;
#   - no binary media committed to git — this script is the committed
#     artifact, same pattern as frontend/tests/ui/asr.spec.js synthesizing its
#     WAV fixture via ffmpeg lavfi in test.beforeAll() rather than checking in
#     an audio file;
#   - GOVERNANCE.md backend tests run with no network (bash run_tests.sh).
#
# Output has a video stream with burned-in ("hard") subtitle text and a
# silent audio track, and zero subtitle streams — ffprobe -select_streams s
# on the output returns nothing, matching a real captionless upload.
#
# Usage: make_fixture.sh <output.mp4>
set -euo pipefail

OUT="${1:?usage: make_fixture.sh <output.mp4>}"

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "color=c=0x1a1a1a:s=640x360:d=6:r=25" \
  -f lavfi -i "anullsrc=r=16000:cl=mono" \
  -filter_complex "[0:v]drawtext=text='HARDSUB LINE ONE':fontcolor=white:fontsize=28:x=(w-text_w)/2:y=h-80:enable='between(t\,1\,3)',drawtext=text='HARDSUB LINE TWO':fontcolor=white:fontsize=28:x=(w-text_w)/2:y=h-80:enable='between(t\,3\,5)'[v]" \
  -map "[v]" -map 1:a -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac -t 6 \
  "$OUT"

echo "[make_fixture] wrote $OUT (6s, 640x360, burned-in text at t=1-3s and t=3-5s, no subtitle stream)"
