# Zibaldone CLI / sidecar execution

This is a routing TODO only. Product contracts remain in the linked authority
files; this document does not redefine API payloads or acceptance criteria.

## Authority map

Authority: `docs/architecture.md#zib-cli-001`
Decision: `ZIB-CLI-001`, `ZIB-CLI-002`, `ZIB-CLI-003`, `ZIB-PACK-001`
Status: active
Verified: 2026-07-22 (live repo audit)

Authority: `docs/design/agent_bridge_spec.md#zib-ab-002`
Decision: `ZIB-AB-002`
Status: A selected and implemented; B/C remain unselected

## TODO

- [x] Add fixed Claude/Codex/Gemini inventory with explicit unavailable states.
- [x] Preserve CLI inventory after failed invocation and expose recovery text.
- [x] Prove `/api/app/model-options` parity across Settings, YouTube, Article,
      and Meeting selectors without paid fallback.
- [x] Repair local sidecar build and package workflow to the active onedir
      `sidecar` resource contract.
- [x] Add backend, frontend, Playwright, Rust/package, and diff evidence.
- [x] Select and implement AB-002-A OKF v0.1 projection; keep activation,
      increment, and evidence-profile work out of scope.

## Open specification / verification gaps

- [x] Provide the Tauri dev `externalBin` artifact expected by
      `tauri.conf.json`; `backend/build_sidecar.sh` now emits the target-suffixed
      artifact and direct Cargo verification passes.
- [ ] Run Windows packaged/dev op-smoke and confirm the same inventory contract.
- [x] Select AB-002-A and verify the OKF bundle, backend, frontend, Playwright,
      and post-repair op-smoke evidence.

## Stop conditions

- Do not silently fallback from a selected `cli:*` route to a paid model.
- Do not copy AB-002-B activation/increment or AB-002-C evidence-profile
  behavior into runtime.
- Do not merge or push from this execution slice.
