# Contributing

Zibaldone is a **one-maintainer, portfolio-grade personal product**. It is open
source so the engineering can be read, built, and reused — not because it seeks a
community roadmap. Expectations, plainly:

- **Best-effort triage.** Issues and PRs are read when time allows. No SLA.
- **Scope is frozen around the maintainer's real workflow.** Feature requests that
  don't fit it will likely be declined — fork freely, the MIT license means it.
- **Bug reports are welcome**, especially with reproduction steps and the app log
  (Settings → open log folder).

## Working on the code

- Read `docs/architecture.md` first — it is short and current.
- Every change must keep the verification suite green:
  backend `unittest discover tests`, frontend `vitest` + `vite build`,
  `playwright test`, and `cargo test --lib` for the shell.
- The API surface is pinned by `backend/tests/test_api_surface_contract.py`.
  Adding or changing an endpoint means updating the contract deliberately.
- Behavior-affecting changes need a test that fails without them.

## Style

- Match the surrounding code. Comments explain *why*, one line, only where the
  code can't say it.
- Conventional Commits (`feat:`, `fix:`, `refactor:` …).
