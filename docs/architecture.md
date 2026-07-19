# Architecture

A 30-minute tour for engineers. Everything here is verifiable in the code; file
references are clickable from the repo root.

## Shape

Three processes, one trust boundary:

```
React (webview) ──HTTP + bearer──▶ FastAPI sidecar (PyInstaller onedir, 127.0.0.1:8766)
      ▲                                    ▲
      │ invoke                             │ spawn / reap / respawn
      └──────────── Tauri shell (Rust) ────┘
```

- The **Tauri shell** generates a per-launch session token, exports it to the
  sidecar's environment, and hands it to the webview via an `invoke` command.
  Every non-health API call must carry it; the backend binds to loopback only.
- The **sidecar** is a PyInstaller `--onedir` tree (executable + `_internal/`)
  bundled as a Tauri resource: FastAPI app assembled in
  [`backend/main.py`](../backend/main.py) (~100 lines — bootstrap, middleware,
  router mounts) over feature routers and services. It ships as a directory rather
  than a single `--onefile` binary because onefile re-extracts its ~200 MB payload
  to a temp dir on *every* launch; shipping the tree unpacked cut cold start
  (spawn → `/api/health`) from ~1.3 s to ~0.6 s (local Linux measurement).

## Sidecar lifecycle (the interesting part)

A desktop app that manages its own backend inherits a failure mode servers don't
have: **orphans**. A force-quit skips the exit handler; the old sidecar survives,
squats the fixed port with a *stale* session token, and every request from the
next launch returns 401 — indistinguishable, to a user, from a broken install.
This happened on a real machine during acceptance testing.

The reap in [`lib.rs`](../frontend/src-tauri/src/lib.rs) is therefore two-layered:

1. **Recorded-PID reap** — the pid we wrote last run, killed only after a
   process-name check (guards against PID reuse).
2. **Port sweep** — any process *listening on the sidecar port* is a candidate;
   each is name-verified as one of our sidecar binaries before being killed.
   This catches orphans whose pid escaped the file (e.g. the pid file was
   overwritten by a later spawn while an older sidecar survived).

Spawn differs by build: **dev** launches a source-backed shell sidecar via Tauri's
`externalBin` (no rebuild between edits); **release** resolves the onedir executable
under the app's resource dir and spawns it directly with `std::process` — the shell
capability scope can't statically express a per-machine resource path, so this
mirrors `open_log_dir`'s intentional Rust-side `Command`. Reaping stays identical
across both: it keys off the recorded pid, name-verified.

The same philosophy covers updates: installing kills the sidecar first (Windows
file locks), and a failed install **respawns** it so the session keeps a working
backend. All of this is under `cargo test --lib`.

## Request pipeline

Each intake lane is a router + service pair under
[`backend/routers/`](../backend/routers) and [`backend/services/`](../backend/services):

| Router | Owns |
|---|---|
| `capture` | YouTube fetch → captions/ASR → translate → summarize → save |
| `meetings` | audio job lifecycle, 3-tier ASR, timestamped distill, model downloads |
| `library` | vault read/write, search, inbox/radar intake, media playback |
| `settings` | model options, cost caps, keys, update token |
| `readiness` | environment probes (vault, ASR runtime, caption reachability) |

## Agent Bridge

The Agent Bridge is a manual, local-only projection from the configured
Markdown vault to `_zibaldone/agent-index/`. It emits an agent-readable
`index.md` plus a machine-readable `manifest.json`; the vault remains the
authority and the projection never rewrites source notes. The route is owned by
the library router (`GET /api/app/agent-index/status` and
`POST /api/app/agent-index`) and is intentionally metadata-only: no LLM,
connector, scheduler, telemetry, or network call is involved.

The full contract is in
[`docs/design/agent_bridge_spec.md`](design/agent_bridge_spec.md).

Long work (meeting ASR) runs as **background jobs with polling**, disk-persisted
state (crash → `interrupted`, retryable), a transcript **checkpoint** keyed by
audio content + engine (retry never re-transcribes an unchanged file), and
cooperative cancellation at stage boundaries.

## Provider abstraction & the no-key ladder

[`providers.py`](../backend/providers.py) exposes one call:

```python
chat_complete(model=..., prompt=..., system=..., json_mode=..., json_schema=...)
```

The model id prefix routes it: `llamacpp:` (built-in local runtime), `cli:`
(subscription CLI subprocess, **off by default** — terms-of-service gray zone,
opt-in setting), or a cloud SDK (OpenAI/Anthropic/Google). Keyless routes
(`llamacpp:`, `cli:`) skip the key check; usage is normalized so the cost page can
truthfully report $0 for local routes.

Two hard rules learned the expensive way:

- **Never trust format compliance.** JSON is requested via native structured
  output where the provider supports it, but the caller always re-extracts and
  re-validates; Traditional-Chinese output is enforced by a post-processing pass,
  not by prompt hope.
- **No timestamp, no claim.** The distill prompt requires `[mm:ss]` attribution
  per item; unattributable items are dropped. The cloud ASR path was switched to
  a model that returns real segment timestamps after the cheaper default was
  caught fabricating `[00:00]` anchors.

The **built-in runtime** (spec C) is the keyless local path: a pinned llama.cpp
release (~15 MB) plus a quantized `gemma-3-4b-it` model (~2.4 GB) are downloaded on
first use with `.part` + atomic-rename semantics — a half-download never looks
installed. Neither ships in the installer (which keeps the release budget — warn
95 MB / fail 110 MB — CI-enforced); once installed, `llamacpp:gemma-3-4b-it` is the
default `translate` model, with cloud as the configured fallback.

The capture lane remains usable when the operator intentionally skips that
optional download and has no cloud key: Chinese OCR is treated as already
translated, and an unavailable translation/summary route produces an editable
**evidence draft** from the captured text. It is labelled as pending manual
review, never presented as AI output, and still requires the normal human review
gate before a note is written.

## Testing as architecture

- **Surface contract**: all 76 endpoint method/path pairs are pinned in one test.
  Router refactors (this codebase was split from a 3,700-line `main.py` in six
  verbatim-move batches) can't silently change the API.
- **Layers**: 320+ backend unit tests (no network, providers mocked), 48 frontend
  unit tests, 27 Playwright E2E cases against a real spawned backend, Rust
  lifecycle tests, plus a product-readiness check (tracked-tree size, forbidden
  paths, artifact budget) that runs in CI and at release.
- **Release gating**: a `v*` tag runs the full CI suite before any packaging job;
  artifacts get updater signatures (minisign) even though OS code-signing is
  deliberately not purchased — the tradeoff is documented in the install guides
  rather than hidden.

## What is deliberately absent

- No accounts, no telemetry, no server component.
- No plugin system, no roadmap voting — scope is the maintainer's real workflow.
- No paid signing certificates; the first-launch friction is documented honestly.
