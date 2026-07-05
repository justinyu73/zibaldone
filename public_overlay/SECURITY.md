# Security Policy

Zibaldone is a local-first desktop app maintained by one person on a best-effort
basis. There is no bug-bounty program and no response-time SLA.

## Reporting

Open a **GitHub security advisory** (preferred) or a private report via the
repository's Security tab. Please include reproduction steps and impact.

## What the app does with your data

- Notes are written only to the vault folder you choose; nothing is uploaded
  unless you explicitly run a cloud-model action.
- Provider API keys are stored in your local user config, never returned in
  plaintext by the API, and never written to logs.
- The UI↔backend channel is guarded by a per-launch session token; the backend
  binds to `127.0.0.1` only.
- No telemetry.

See `docs/privacy-and-network.md` for the full network-behavior contract.
