<a id="zib-arch-001"></a>
# Architecture

**Authority:** canonical Zibaldone architecture and design map (`ZIB-ARCH-001`).
Detailed feature contracts are authoritative only within their named scope and
must be linked from this file. Session Hub strategy and handoff files are
summary/routing layers, not product authority.

**Status:** active · **Updated:** 2026-07-21

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
2. **Port sweep** — any process *listening on the sidecar port* is a candidate.
   Current PyInstaller sidecars are name-verified before being killed. A legacy
   Python/uvicorn launcher is eligible only when both its command identifies the
   legacy sidecar and its public loopback health response has the Zibaldone
   fingerprint; an arbitrary Python or HTTP process is never sufficient. This
   catches orphans whose pid escaped the file (e.g. the pid file was overwritten
   by a later spawn while an older sidecar survived).

Spawn differs by build: **dev** launches a source-backed shell sidecar via Tauri's
`externalBin` (no rebuild between edits); **release** resolves the onedir executable
under the app's resource dir and spawns it directly with `std::process` — the shell
capability scope can't statically express a per-machine resource path, so this
mirrors `open_log_dir`'s intentional Rust-side `Command`. Reaping uses the same
protected ownership rule across both modes: current binary name, or legacy
launcher command plus the Zibaldone health fingerprint.

The same philosophy covers updates: installing kills the sidecar first (Windows
file locks), and a failed install **respawns** it so the session keeps a working
backend. All of this is under `cargo test --lib`.
The package and release workflows additionally start the sidecar copied into the
desktop bundle, then prove `/api/health` and the session-protected cost API before
an artifact may proceed to the size or upload gates.

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

<a id="zib-ab-001"></a>
## Agent Bridge（ZIB-AB-001）

The Agent Bridge is a manual, local-only OKF v0.1 projection from the
configured Markdown vault to `_zibaldone/agent-index/`. It emits an OKF root
`index.md` plus derived concept Markdown; the vault remains the authority and
the projection never rewrites source notes. The route is owned by the library
router (`GET /api/app/agent-index/status` and `POST /api/app/agent-index`) and
is intentionally metadata-only: no LLM, connector, scheduler, telemetry, or
network call is involved.

The full contract is in
[`docs/design/agent_bridge_spec.md`](design/agent_bridge_spec.md).

Long work (meeting ASR) runs as **background jobs with polling**, disk-persisted
state (crash → `interrupted`, retryable), a transcript **checkpoint** keyed by
audio content + engine (retry never re-transcribes an unchanged file), and
cooperative cancellation at stage boundaries.

<a id="zib-ab-002"></a>
## ZIB-AB-002 — Agent Bridge v2 research: OpenWiki / OKF alignment

**Status:** `ZIB-AB-002-A` adopted and implemented; B/C remain research/open.
[`ZIB-AB-001`](#zib-ab-001) remains the operational boundary.

Re-verified 2026-07-21: OpenWiki has widened past the pattern reference recorded
in the v1 decision — it now ships a CLI with code and personal modes, emits
Google's Open Knowledge Format (OKF) v0.1 bundles, regenerates directory indexes
deterministically, keeps a per-run change log, and writes agent instruction
files that make coding agents consult the wiki. Zibaldone now matches the OKF
format for its metadata-only projection; activation and per-note change logs
remain unselected.

The comparison, the candidate slices (OKF conformance; activation and increment
layer; evidence-anchored concept profile), their tradeoffs, and the unresolved
questions are held in
[`docs/design/agent_bridge_spec.md`](design/agent_bridge_spec.md#zib-ab-002),
with the active A contract at
[`#zib-ab-002-a`](design/agent_bridge_spec.md#zib-ab-002-a).

Sequencing note: [`ZIB-CLI-001`](#zib-cli-001) remains a separate release slice;
AB-002-A does not authorize B or C.

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
installed. Neither ships in the installer. CI enforces separate desktop budgets:
Windows warns at 95 MB and fails at 110 MB; macOS warns at 160 MB and fails at
200 MB because its DMG and updater archive compress the same onedir sidecar less
efficiently. Once installed, `llamacpp:gemma-3-4b-it` is the default `translate`
model, with cloud as the configured fallback.

The capture lane remains usable when the operator intentionally skips that
optional download and has no cloud key: Chinese OCR is treated as already
translated, and an unavailable translation/summary route produces an editable
**evidence draft** from the captured text. It is labelled as pending manual
review, never presented as AI output, and still requires the normal human review
gate before a note is written.

<a id="zib-cli-001"></a>
## ZIB-CLI-001 — Next-release specification map: subscription CLI routes

**Status:** queued defect correction from the v0.8.4 Windows acceptance pass;
implement as one release slice, then verify with backend contract tests,
frontend tests, Playwright, and human op-smoke.

<a id="zib-cli-002"></a>
### ZIB-CLI-002 — Gemini is missing from the subscription CLI inventory

The supported subscription CLI set is exactly:

```text
cli:claude   Claude（訂閱）
cli:codex    Codex（訂閱）
cli:gemini   Gemini（訂閱）
```

After the user enables subscription CLIs and presses **儲存模型/上限**, the
Settings page must not silently omit Gemini. The UI must show a three-item
inventory with an explicit state for each item: `可用`、`未安裝`、`未登入／呼叫失敗`
or `不可用於目前平台`. A missing executable may be disabled for execution, but
must not be presented as if Gemini were unsupported.

Windows packaged-app detection must cover the process PATH and the normal npm
global command locations, including the `.cmd` entrypoints. Detection and
invocation are separate checks: finding `gemini` is not proof that it is logged
in, and a failed call must report the provider-specific reason without removing
the provider from the inventory.

<a id="zib-cli-003"></a>
### ZIB-CLI-003 — CLI models do not reach the three capture lanes

The model-options response is the single registry for both Settings and the
three human-facing capture lanes:

```text
GET /api/app/model-options
  translate: [...]
  summary:   [...]
  cli_inventory: [claude, codex, gemini with availability state]
```

When a supported CLI is available and enabled, its `cli:*` model id must be
present in every applicable task list. The YouTube, Article, and Meeting
modules must consume this same response for their model pickers; no module may
maintain a cloud-only or hardcoded model list. In particular, selecting
`cli:codex` in Settings must make Codex selectable in the translation and/or
summary controls used by all three modules, according to the task each module
actually executes.

The selected route must be persisted by task, reflected in the module's cost
route as `訂閱・零成本`, and passed to the same backend provider router. A stale
model-options response, a missing CLI executable, or a failed CLI login must
produce an explicit unavailable state and recovery instruction; it must not
silently fall back to a paid cloud model.

`cli_inventory` is returned even when subscription CLI display is disabled. It
contains exactly the three supported ids and, for each item, the stable fields
`id`, `label`, `state`, `state_label`, `selectable`, and `recovery`. `state` is
one of `available`, `not_installed`, `call_failed`, or
`unsupported_platform`; only `available` items enter the translate/summary
select lists. `available` means the executable was detected, not that login was
proven. A failed invocation may project `call_failed` for the current sidecar
session, but it must keep the item in the inventory and return the provider
error to the caller.

### Single-slice acceptance map

1. With Claude, Codex, and Gemini available, enabling and saving the setting
   exposes all three in Settings and in the applicable YouTube／Article／Meeting
   selectors.
2. With only Claude and Codex available, Gemini remains visible as
   `未安裝／不可用` rather than disappearing; Claude and Codex remain selectable.
3. Windows packaged and dev launches return the same CLI inventory and model
   ids; PATH differences do not change the product contract.
4. Toggling the setting without saving keeps all CLI routes inactive and shows
   the existing unsaved warning. Saving refreshes the model registry once and
   all three modules observe the new state without an app restart.
5. A selected `cli:*` route reaches `providers.chat_complete()` with the same
   model id, records zero app-side cost, and surfaces CLI exit/login errors
   without writing a note.
6. Add regression coverage for the three CLI inventory states, the
   `/api/app/model-options` lane parity, Settings save/refresh, and Playwright
   checks for YouTube／Article／Meeting model selection before the next release.

<a id="zib-pack-001"></a>
## ZIB-PACK-001 — Desktop sidecar packaging invariant

**Status:** active · **Decision:** the release sidecar is a PyInstaller
`--onedir` tree bundled as the Tauri `sidecar` resource. The local build helper,
package workflow, release workflow, and Rust resolver must all use this same
layout. A onefile executable placed only under `binaries/` is not a valid
release artifact for the current Rust loader.

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
