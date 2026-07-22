# Agents

Canonical rules: **GOVERNANCE.md** — read it first.
Current state: **CURSOR.md** — read it on every session start.

## Build / Test (inline for Codex compatibility)

```bash
# Backend
cd backend && bash run_tests.sh

# Frontend
cd frontend && npm test
npx playwright test

# Desktop bundle
bash build_desktop.sh
```

## Everything Else

See GOVERNANCE.md for branch discipline, commit format, forbidden actions,
directory map, and docs retirement policy.
