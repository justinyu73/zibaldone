# Fixture: captionless hardsub sample

Full gap analysis and acceptance criteria this fixture supports:
`docs/evidence/2026-08-14-win-asr-ocr-hardsub-acceptance.md`.

## What

`make_fixture.sh` generates a 6-second, 640x360 MP4 with burned-in
("hard") subtitle text — `HARDSUB LINE ONE` at t=1-3s, `HARDSUB LINE TWO`
at t=3-5s — a silent mono audio track, and **zero subtitle streams**
(`ffprobe -select_streams s` returns nothing). It stands in for a real
video with hardsub and no CC/auto-captions.

## Why generated, not downloaded

The task's reference case is a real public video
(`https://youtu.be/OQ09v_T81I8`, confirmed via `yt-dlp --skip-download`
on 2026-08-14: 719s, `subtitles: []`, `automatic_captions: []` — genuinely
no CC of any kind). It is **not** used as the automated-test fixture:

- not reproducible/offline — depends on the video staying up, public, and
  unchanged, plus live network at test time;
- `bash backend/run_tests.sh` runs with no network (`GOVERNANCE.md`);
- committing downloaded YouTube video bytes into git is a redistribution
  problem this project doesn't need to take on.

Instead, only the *generator script* is committed — the same pattern
`frontend/tests/ui/asr.spec.js` already uses for its audio fixture
(`ffmpeg -f lavfi ... sine=...` synthesized in `test.beforeAll()`, never
checked into git). The real video remains useful as a one-time **manual**
sanity check that the packaged app handles real-world content, not as a
CI dependency.

## How to (re)generate

```bash
bash test/fixtures/hardsub_no_cc/make_fixture.sh /tmp/hardsub_no_cc_sample.mp4
```

Requires `ffmpeg` on PATH (already a project dependency; CI runners and
the packaged app both provision it — see `backend/ffmpeg_runtime.py`).

## Verified expected output (2026-08-14)

Ran the real production code path, not a mock:

```
backend$ source .venv/bin/activate
backend$ python3 -c "
from local_ocr import extract_text
data = open('/tmp/hardsub_no_cc_sample.mp4.frame_t2.png', 'rb').read()  # frame extracted at t=2s
print(extract_text(data))
"
HARDSUBLINEONE
```

`backend/local_ocr.py`'s RapidOCR engine drops the spaces from spaced-out
capitalized text — expected, not a bug. Assertions against this fixture
should check for the substrings `HARDSUB` and `LINEONE` / `LINETWO`
(case-insensitive, whitespace-insensitive), not exact string equality.

## Using it

- **Unit/E2E regression tests** (fast, no real OCR run): mock the
  `production-extractor` / `video-audio-asr` HTTP responses directly, as
  `frontend/tests/ui/capture.spec.js` already does — the video file itself
  isn't needed to test draft-generation and error-handling logic.
- **Op-Demo / Windows packaged acceptance** (real OCR run, human- or
  smoke-script-driven): point the packaged app's hardsub OCR button at a
  local copy of the generated MP4 (the video capture lane accepts a
  YouTube URL only today — see gap list in the evidence doc above for the
  local-file-input gap this implies) and confirm the extracted text
  contains `HARDSUB` / `LINEONE` / `LINETWO`.
