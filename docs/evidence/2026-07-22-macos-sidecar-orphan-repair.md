# macOS sidecar orphan repair — evidence

Authority: `docs/architecture.md#zib-arch-001`  
Decision: `ZIB-ARCH-001`  
Status: locally verified; macOS release and human acceptance pending  
Verified: 2026-07-22

## Field diagnosis

The operator-provided macOS app log shows a repeated failure after the app was
updated to v0.8.5:

- `2026-07-21 07:21:52` — `Errno 48 ... 127.0.0.1:8766: address already in use`.
- The same bind failure recurs at `2026-07-21 09:06:15`, `2026-07-22 09:27:16`,
  `2026-07-22 12:35:28`, and after `installing update 0.8.5` at
  `2026-07-22 12:36:28`.
- Earlier successful starts show the sidecar and `/api/app/cost-summary` both
  return 200, so the Cost page `Load failed` is a downstream symptom of the
  sidecar failing to bind, not a cost-cap or key failure.

The port sweep previously identified only current PyInstaller executable names.
An older source-backed Python/uvicorn sidecar can own the fixed port while being
reported by macOS as `Python`, so it was deliberately ignored by the old
name-only safety check and every new sidecar then exited on bind.

## Repair

- `frontend/src-tauri/src/lib.rs` now allows legacy reaping only when both the
  process command identifies the old sidecar launcher and a loopback
  `/api/health` response contains the Zibaldone health fingerprint. Arbitrary
  Python processes and arbitrary HTTP listeners remain ineligible.
- `scripts/smoke_bundled_sidecar.sh` starts the exact PyInstaller sidecar copied
  into a desktop build and proves both `/api/health` and token-protected
  `/api/app/cost-summary`.
- `.github/workflows/package.yml` and `.github/workflows/release.yml` run that
  smoke before artifact size/upload gates, including directly from the macOS
  `.app` resource path.
- Settings now reports `成本狀態未知` instead of a false-green cost state when
  the summary request is unavailable.

## Local verification

| Check | Result |
| --- | --- |
| `CARGO_TARGET_DIR=/tmp/zibaldone-cargo-test cargo test --lib --locked` | 6 passed |
| `bash scripts/smoke_bundled_sidecar.sh frontend/src-tauri/target/release/sidecar/video-intake-fastapi-sidecar 18768` | PASS: health + protected cost summary |
| `npm test` | 48 passed |
| `E2E_BACKEND_PORT=8122 E2E_FRONTEND_PORT=5175 npm run test:ui -- tests/ui/settings.spec.js` | 4 passed |
| `git diff --check` | pass |

## Remaining acceptance boundary

This evidence proves the code path and Linux-built resource smoke only. A new
macOS release must still complete the workflow's native macOS bundle smoke, then
the operator must confirm Settings shows `後端：已連線` and Cost monitoring loads.
