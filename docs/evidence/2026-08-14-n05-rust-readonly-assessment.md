# N05 — Rust read-only assessment: decision table

Status: read-only evaluation, no product code touched. Every benchmark cell
below is a number this session actually produced in this sandbox (Python
3.12.3, Linux, `backend/.venv`, system `ffmpeg`/`ffprobe`), not an estimate.
Where something could not be measured here, the cell says so and states why,
per task instructions — no invented numbers.

Scope: this evaluates 5 named candidates only, against the existing Python
backend + Rust `frontend/src-tauri` shell. It does not recommend or evaluate
a broader rewrite. React, FastAPI, the Python sidecar, and existing tests
stay as-is regardless of outcome.

Precondition note: N05 was dispatched with "N04 done, 6/6 acceptance PASS"
as its start condition. A pre-start check against
`docs/evidence/2026-08-14-win-asr-ocr-hardsub-acceptance.md` §3 found
criterion #5 (OCR local/cloud auto-switch on `OPENAI_API_KEY`,
`backend/production_extractor.py:392`) still open. Coordinator confirmed:
criterion #2 is satisfied (B1 was out of N03's approved scope), criterion #5
is real and will be routed to the owner separately, and N05 should proceed
under its original scope regardless. This table does not re-litigate that
gap.

## Architecture context: does Tauri `command` + `invoke()` fit these candidates?

Read `frontend/src-tauri/src/lib.rs` in full and grepped `invoke(` across
`frontend/src`. Current state: **4** `#[tauri::command]` functions exist
(`sidecar_ready`, `sidecar_session_token`, `install_app_update`,
`open_log_dir` — `lib.rs:635`), and exactly **3** `invoke()` call sites in
the frontend (`frontend/src/app/api.js:29`,
`frontend/src/features/settings/UpdateSettings.jsx:62,75`) — all app-shell
concerns (session token, self-update, log directory). None of candidates
1–4 go through `invoke()` today; the frontend reaches them over HTTP to the
Python sidecar (`fetch`/`apiFetch`). Candidate 5 (sidecar spawn/reap/respawn)
runs entirely inside Rust's own `setup()` hook and is never invoked from JS
at all.

Consequence for every row below: moving any of candidates 1–4 to Rust is not
a language swap alone — it means adding new `#[tauri::command]` handlers,
new `invoke()` call sites replacing existing `fetch()` calls, and keeping a
Python-side fallback (self-hosted OS support matrix, see per-row notes) or
deleting the sidecar route outright. That migration cost is real and is
priced into the "Windows/macOS complexity" column; it does not by itself
argue for or against a given candidate, since the benchmark/benefit columns
already come out negative for all 4 independent of this cost.

## Decision table

| candidate | benchmark (measured, method) | benefit if moved to Rust | binary-size impact | Windows/macOS complexity | rollback | recommendation |
|---|---|---|---|---|---|---|
| **1. Runtime download, SHA-256, atomic install** (`backend/ffmpeg_runtime.py`, `backend/asr_runtime.py`) | Measured `hashlib.sha256` (1 MiB chunks, same shape as `asr_runtime._stream_hash`) vs `sha256sum` (coreutils/C) on synthetic 10/50/150 MB files: 150 MB → Python 75.4 ms (1989 MB/s) vs native 78.8 ms (1905 MB/s) — **Python is 0.96× native, i.e. as fast**. Confirmed why: `hashlib.sha256().__class__.__module__ == "_hashlib"` — CPython's hashlib calls OpenSSL `libcrypto` (C), it is not a Python loop over bytes. Atomic install itself is `Path.replace()`, one `rename(2)` syscall (see candidate 4 for its measured cost: 21–51 µs, size-independent). | **~0.** The CPU part (hashing) is already native-speed; the slow part of "download" is network I/O, which no language change affects and which this session did not exercise live (see Scope notes). Rust would not make the `.part`→verify→rename sequence faster. | **Near-zero marginal.** `Cargo.lock` (frontend/src-tauri) already resolves `reqwest 0.13.4`, `hyper`/`hyper-rustls`, `sha2 0.10.9`, `zip 4.6.1`, `tar 0.4.46`, `flate2`, `minisign-verify` — all pulled in transitively by the already-shipping `tauri-plugin-updater`. A Rust download+verify+extract path would reuse these, not add new crates. | Current Rust TLS stack (`hyper-rustls`, proven in the shipping updater) sidesteps the exact class of bug this repo already hit twice on the Python side — packaged app has no system CA store, fixed with a manual `certifi` context (`eccb550`, and `asr_runtime.py`'s own `_ssl_context` import). That's a real, historically-evidenced advantage, but it is fixable in Python directly (already was, twice) without a language migration. Needs 2 new `#[tauri::command]`s + `invoke()` replacing the existing `/app/ffmpeg/status`+`/install` and `/app/asr-runtime/status`+`/install` HTTP polling the frontend already does. CI already builds/signs on `windows-latest`/`macos-latest` (`.github/workflows/package.yml` matrix + signing-key step) so no new cross-compile setup, but a Python-side fallback would still be needed for any platform gap (e.g. macOS whisper.cpp, which has no precompiled binary at all — `asr_runtime.py`'s own docstring). | Keep Python path as-is; if a Rust path were added it would sit behind a new endpoint, not replace the existing one until proven — trivial to delete the new command and revert `Cargo.toml` if abandoned. | **defer** — no measured CPU/perf case; the one real advantage (TLS/CA handling) is already solved in Python. Revisit only if Rust ever takes ownership of *all* app networking, where the marginal crates are already free. |
| **2. ffmpeg/ffprobe discovery** (`backend/ffmpeg_runtime.py::resolve()`) | Called the real `resolve()` 10,000× in-process: 354.75 ms total → **35.47 µs/call**. Compared against spawning `ffmpeg -version` (the thing `resolve()`'s result is used to launch) 20×: mean **26.5 ms**. `resolve()` is 748× cheaper than one process spawn it enables. | **~0.** `resolve()` is 2–3 `stat()`/`access()` syscalls plus an optional `shutil.which` PATH scan — already negligible against the process-spawn cost surrounding every actual use of its result, which is identical in Rust (spawning a process costs what the OS charges, regardless of caller language). | Zero — pure path-checking logic, standard library only either language. | Needs a new `#[tauri::command]`+`invoke()` to replace the `/api/health`→`production_extractor.tools.ffmpeg.available` field the frontend already reads (gap-doc criterion #2). Would split "is ffmpeg ready" reporting across two languages for a function that costs microseconds. No new build/signing surface. | Trivial function; a revert is a 1-file diff either direction. | **reject** — 748× measured margin proves this was never the hotspot; not worth fragmenting the readiness-reporting path for it. |
| **3. Frame extraction / OCR preprocessing** (`backend/production_extractor.py` sampling loop + `backend/local_ocr.py`) | Ran the *actual* per-frame pipeline against the synthesized hardsub fixture (`test/fixtures/hardsub_no_cc/make_fixture.sh`, real `ffmpeg` subprocess with the exact args at `production_extractor.py:430-451`, then real `local_ocr.extract_text()`): ffmpeg 1-frame extract mean **114.1 ms**; RapidOCR/ONNXRuntime inference (warm) mean **323.6 ms** (min 245.5 ms; cold engine load once per process: 275.5 ms). Split of per-frame wall time: **~26% ffmpeg / ~74% OCR inference**. `sha256` of the resulting 26 KB frame: **24.8 µs** — noise. `sample_count` is capped at 6 frames/run (`CAPS["max_sampled_frames"]`, `production_extractor.py:22`). | **~0 for anything Python-attributable.** Both cost centers are already native code reached via subprocess (ffmpeg, a C binary) and library binding (RapidOCR → ONNXRuntime, C++). The Python "glue" around them (building dicts, reading bytes, hashing 26 KB) is a rounding error against 430 ms/frame of already-native work. Moving *only the glue* to Rust saves nothing measurable; moving the OCR *engine* itself to Rust is a from-scratch reimplementation, explicitly out of this task's scope. | **Large if attempted for real, not "impact" — a new dependency class.** Measured the currently-shipped Python OCR stack directly in this sandbox: `onnxruntime` package installed = 58 MB (core `.so` alone 25.9 MB), `rapidocr_onnxruntime` (incl. bundled detection/recognition/classification models) = 16 MB → **~74 MB total**. A Rust OCR path needs an equivalent ONNX Runtime native library + model files of the same order, or a from-scratch pure-Rust OCR stack (immature/unproven for this use case) — nothing comparable exists in `Cargo.lock` today (no `image`, `onnxruntime`, or OCR-adjacent crate is resolved). | Would duplicate, in Rust, exactly the per-platform native-binary problem `asr_runtime.py`'s docstring already documents solving for whisper.cpp (per-OS builds, Windows per-CPU-microarchitecture `ggml-cpu-*.dll` variants). ONNX Runtime redistributables are platform- and often CPU-feature-specific; this is a materially bigger cross-platform packaging problem than candidates 1/2/4, which stay inside `std`/already-vendored crates. | N/A — recommend not starting; nothing to roll back from. | **reject** — measured wall time is 74% inside already-native OCR inference and 26% inside the ffmpeg native binary; zero measured Python hotspot exists, and the only real "Rust-ify OCR" path is a full reimplementation this task is explicitly scoped out of. |
| **4. Large-file hashing / movement** (vault write path — `backend/vault_write.py` `shutil.copy2` backup, `backend/note_rollback.py` `sha256_text`/`_hash_file`, `backend/capture_inbox.py::_pdf_id` sha256) | Found actual call sites first (grep), then measured each shape for real: `shutil.copy2` at note scale (4 KB) = **0.165 ms**; at scanned-PDF scale (20 MB synthetic) = **12.0 ms** (1664 MB/s — OS fast-copy path, not a Python byte loop). `os.replace` (atomic rename, used by `capture_inbox.dismiss`/`inbox.py`/`asr_runtime.py`/`ffmpeg_runtime.py` alike): **21–51 µs regardless of file size** (`rename(2)` is O(1), doesn't touch content). `note_rollback.sha256_text` on a realistic 4000-char note, ×10,000: **2.22 µs/call**. | **~0.** Every real call site in the vault-write path operates on note-scale (KB) or, at most, scanned-PDF-scale files — `capture_inbox.py` itself caps its own scan at `MAX_FILE_BYTES = 512 * 1024` (`capture_inbox.py:19`). Nothing in the actual call graph is "large" in a sense where hashing/copy throughput is perceptible: every measured operation here is a one-shot sub-15 ms call, not a loop. The candidate's name ("large-file") does not match what the code actually does. | Zero marginal — `sha2` is already resolved in `Cargo.lock` (see candidate 1); no new crate needed even in principle. | Would need new `#[tauri::command]`s replacing Python vault-mutation endpoints, splitting one conceptual operation (write a note, back it up, verify it) across two processes/languages for zero measured gain — worse for maintainability, not better. | N/A. | **reject** — no file in the actual call graph is large enough for this to matter; every measured op is sub-15 ms and one-shot. |
| **5. Sidecar lifecycle / process supervision** (`frontend/src-tauri/src/lib.rs` spawn/reap/respawn incl. N03's auto-restart, `MAX_SIDECAR_RESTARTS = 5`, `lib.rs:35`) | **This is already Rust** — confirmed by reading `lib.rs` in full and a repo-wide grep: no Python equivalent exists to migrate *from*. What was measured instead is the OS-native floor the *current* Rust code already pays: a raw TCP connect + HTTP GET matching `loopback_health_is_zibaldone_sidecar`'s own shape (`lib.rs:164-187`) against a local dummy server = mean **0.13 ms**; spawning `lsof` (the same class of external-command cost `port_listener_pids` pays on unix, `lib.rs:225-237`) = mean **14.4 ms** — same order as the `ffmpeg -version` spawn in candidate 2. Code-read evidence: `reap_previous_sidecar`/`kill_current_sidecar`/the restart loop use explicit `thread::sleep(300ms)`/`sleep(500ms)` debounce delays (`lib.rs:268,284,339,399,538`) — deliberate design, not incidental slowness. | **N/A — nothing to migrate.** The one measured cost center specific to this path (`lsof` spawn, 14.4 ms) is OS-process-spawn-bound, identical regardless of language, same as candidate 2's finding. The sleep-based debounces are a design choice; no rewrite changes what `sleep(300ms)` costs. | N/A. | N/A — already ships cross-platform today: `cfg(unix)`/`cfg(not(unix))` branches for `kill`/`ps`/`lsof` vs `taskkill`/`tasklist` + `CREATE_NO_WINDOW`, already exercised in the `windows-latest`/`macos-latest` CI matrix (`.github/workflows/package.yml`) per the N04 gap doc's own citation of `scripts/smoke_bundled_sidecar.sh` running on `windows-latest`. | N/A. | **reject** — not because the idea is bad, but because it is already done; there is no Python implementation of this candidate to move. Flagging this explicitly so it isn't re-proposed as if it were still open. |

## Appendix: measurement method

Benchmark script: `bench.py` (session scratchpad, not part of the repo) —
imports the *real* `backend/ffmpeg_runtime.py` and `backend/local_ocr.py`
modules (via `sys.path`), runs the *real* `test/fixtures/hardsub_no_cc/
make_fixture.sh` fixture generator, and shells out to the *real* system
`ffmpeg`/`sha256sum`. Full raw output:

```
=== 1. SHA-256 throughput (candidates 1 + 4) ===
    10 MB  python hashlib.sha256:     5.5 ms ( 1802.8 MB/s)  |  sha256sum(C):     6.7 ms ( 1500.5 MB/s)  |  ratio python/native = 0.83x
    50 MB  python hashlib.sha256:    25.3 ms ( 1977.9 MB/s)  |  sha256sum(C):    26.4 ms ( 1896.9 MB/s)  |  ratio python/native = 0.96x
   150 MB  python hashlib.sha256:    75.4 ms ( 1989.0 MB/s)  |  sha256sum(C):    78.8 ms ( 1904.5 MB/s)  |  ratio python/native = 0.96x
  hashlib backend: _hashlib

=== 2. ffmpeg_runtime.resolve() + subprocess spawn floor (candidate 2) ===
  resolve('ffmpeg') x 10000: 354.75 ms total, 35.47 us/call
  (path='/home/jy/.config/yt-note-app/tools/ffmpeg/ffmpeg' — resolved via downloaded copy)
  subprocess spawn 'ffmpeg -version' x20: mean 26.5 ms, min 24.5 ms, max 28.8 ms
  => resolve() itself is 35.47 us; one process spawn is 26.5 ms — spawn dominates by 748x

=== 3. Frame extraction + OCR (candidate 3) ===
  ffmpeg 1-frame extract (scale=1280:-1, real subprocess) x5: mean 114.1 ms, min 114.0 ms
  frame size: 26374 bytes
  sha256 of one frame (26374 bytes): 24.8 us
  local_ocr engine load (first call, model init): 275.5 ms
  local_ocr.extract_text() (RapidOCR/ONNXRuntime, warm) x5: mean 323.6 ms, min 245.5 ms
  OCR result: 'HARDSUB LINE ONE'
  => per sampled frame: ffmpeg extract 26% / OCR inference 74% of wall time

=== 4. vault write: copy2 / os.replace (candidate 4) ===
  shutil.copy2 note (~4 KB): 0.165 ms (24 MB/s)
  os.replace (atomic rename) note (~4 KB): 21.2 us
  shutil.copy2 scanned PDF (~20 MB): 12.016 ms (1664 MB/s)
  os.replace (atomic rename) scanned PDF (~20 MB): 51.0 us
  note_rollback.sha256_text on 4000-char note x10000: 22.2 ms total, 2.22 us/call

=== 5. sidecar lifecycle: OS-native floor (candidate 5, already Rust) ===
  raw TCP connect+GET /api/health x20: mean 0.13 ms, min 0.08 ms
  subprocess spawn 'lsof' (port scan, unix path) x10: mean 14.4 ms
```

Binary-size baseline (measured, not estimated, this sandbox):
`frontend/src-tauri/target/release/app` = 18,282,032 bytes (~17.4 MiB,
unstripped); `target/release/sidecar` (packaged Python onedir tree) =
562 MB; `Zibaldone_0.8.7_amd64.deb` = 228,317,734 bytes (~217.7 MiB). The
Python sidecar dominates total app size by >30×; realistic Rust
crate-size deltas for candidates 1/2/4 (all already-vendored crates, see
table) are noise against that baseline. `Cargo.lock` currently resolves
530 packages total (`grep -c '^name = ' Cargo.lock`).

## Scope notes — what was not measured, and why

- **Live network download** (the actual HTTPS fetch in candidates 1) was
  not exercised. It is I/O-bound (network latency/bandwidth), not a
  CPU/language comparison point — a Rust HTTP client does not fetch bytes
  over the same network link faster than Python's. Benchmarks instead
  isolated the CPU-relevant part (hashing) using synthetic local files.
- **Exact real artifact byte sizes** for the whisper.cpp/ffmpeg release
  archives were not fetched this session (no live download performed) —
  the 10/50/150 MB sweep in candidate 1 brackets plausible sizes rather
  than reproducing one exact figure; treat any specific "the archive is
  X MB" claim elsewhere as `assumption`, not this session's finding.
- **Windows/macOS complexity cells** are grounded in reading the actual
  `cfg(windows)`/`cfg(target_os)` branches already in `lib.rs` and the
  real `.github/workflows/package.yml` CI matrix + signing-key step — not
  in an actual Windows/macOS build run, since this sandbox is Linux-only.
  Where a claim depends on something beyond what the existing code/CI
  directly shows, it is judgment applied to verified code, not a
  measurement.
