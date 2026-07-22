# Zibaldone CLI / sidecar acceptance package

Status: complete for the approved local implementation slice; open gaps are
listed below and are not represented as passed.
Authority: `docs/architecture.md#zib-cli-001`
Decisions: `ZIB-CLI-001`, `ZIB-CLI-002`, `ZIB-CLI-003`, `ZIB-PACK-001`,
`ZIB-AB-002-A`
AB decision packet: `docs/design/agent_bridge_spec.md#zib-ab-002`

This file is an evidence index, not a second specification. Each result below
must contain the exact command, exit code, and a short artifact path or output
digest before this slice is marked complete.

## Required evidence

- [x] Backend contract and unit tests — `bash backend/run_tests.sh`, exit 0,
  334 tests, 1 skipped.
- [x] Frontend unit tests — `cd frontend && npm test`, exit 0, 48/48.
- [x] Frontend production build — `cd frontend && npm run build`, exit 0,
  2307 modules transformed.
- [x] Full Playwright suite —
  `E2E_BACKEND_PORT=8123 E2E_FRONTEND_PORT=5177 npm run test:ui`, exit 0,
  29/29 passed; includes Agent Bridge, Settings, all three capture lanes,
  ASR, inbox, playback, and closure flows.
- [x] Sidecar build/layout check — `bash backend/build_sidecar.sh`, exit 0;
  onedir tree at `frontend/src-tauri/binaries/video-intake-fastapi-sidecar/`.
  The built executable returned HTTP 200 on `/api/health`; packaged
  `/api/app/model-options` returned the fixed three-item inventory and all
  three CLI ids in both translate and summary lists in this host environment.
- [x] Rust lifecycle check — original `cargo test --lib --locked`, exit 0,
  4/4, after `backend/build_sidecar.sh` generated the target-suffixed dev
  externalBin. No config override was needed.
- [x] `git diff --check` — exit 0.
- [x] AB-002-A decision and implementation — `docs/design/agent_bridge_spec.md#zib-ab-002-a`,
  OKF v0.1 root index plus metadata-only concept files; B/C remain unselected.

## Final review

- [x] No API keys, personal vault content, or complete transcripts included
- [x] No silent paid fallback — selected `cli:*` routes now stop at the CLI
  error and have a regression test.
- [x] No merge, push, or PR claimed from local evidence
- [x] Spec truth and live implementation truth reported separately

## Post-repair op-smoke

- [x] Source backend on `127.0.0.1:8780` — health 200; fixed three-item
  inventory returned. E2E mode intentionally keeps CLI selection disabled by
  default, so translate/summary CLI lists were empty.
- [x] Dev externalBin on `127.0.0.1:8781` — health 200; inventory contained
  `cli:claude`, `cli:codex`, `cli:gemini`, and both task lists contained all
  three when enabled.
- [x] Release onedir on `127.0.0.1:8782` — health 200; same inventory and
  translate/summary projection as dev.
- [x] Settings/UI smoke — `E2E_BACKEND_PORT=8786 E2E_FRONTEND_PORT=5176
  npm run test:ui -- tests/ui/settings.spec.js`, exit 0, 3/3 passed; covers
  Settings inventory plus YouTube／Article／Meeting selectors.
- [x] AB-002 Agent Bridge Playwright — `E2E_BACKEND_PORT=8121
  E2E_FRONTEND_PORT=5174 npm run test:ui -- tests/ui/agent-bridge.spec.js`,
  exit 0, 1/1 passed; verifies OKF root/concept output, no new manifest, and
  unchanged source note.
- [x] Post-AB-002 op-smoke — `E2E_BACKEND_PORT=8122
  E2E_FRONTEND_PORT=5175 npm run test:ui -- tests/ui/settings.spec.js`,
  exit 0, 3/3 passed.

## AB-002 decision packet

Authority: `docs/design/agent_bridge_spec.md#zib-ab-002`

- **A — OKF-conformant projection:** additive format interoperability; keeps
  the v1 vault authority boundary, but depends on OKF version/type derivation.
- **B — Activation and increment layer:** additive agent pointer plus change
  log; needs a safe location and an external agent op-demo.
- **C — Evidence-anchored concept profile:** positions Zibaldone as an
  evidence-backed OKF producer; this reopens product scope and v1 boundaries.

Decision: **A selected**. `ZIB-AB-002-A` is implemented as an OKF v0.1
metadata-only projection. B (activation/increment) and C (evidence-anchored
concept profile) remain unselected and are not implemented.

## Open gaps / handoff

1. Windows packaged/dev op-smoke is not proven on this Linux/WSL host; the
   selected A contract is verified on the local backend/frontend path.

## Review boundary

The working tree remains on `agent/public-release-0-8-4` at `a58f4b9`; no
commit, push, PR, or merge was performed by this acceptance run. Pre-existing
dirty files were preserved and are not silently attributed to this slice.
