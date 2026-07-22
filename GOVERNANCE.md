# Governance — Zibaldone

Zibaldone turns YouTube videos, web articles, and meeting audio into structured,
timestamped Markdown notes in your local vault (Obsidian-compatible). Tauri desktop
app with a React frontend and a FastAPI Python backend sidecar. Local-first; works
without any API key.

## Build / Test / Run

```bash
# Backend (Python, venv)
cd backend && source .venv/bin/activate
pip install -r requirements.txt
bash run_tests.sh                        # stdlib unittest, no network
VIDEO_INTAKE_FASTAPI_PORT=8766 python sidecar_main.py  # app dev sidecar on :8766

# Frontend (Node 22, npm)
cd frontend && npm install
npm run dev:wsl                          # Vite dev on :5173
npm test                                 # Vitest unit tests
npx playwright test                      # E2E (needs backend running)

# Desktop bundle
bash backend/build_sidecar.sh             # generate dev externalBin + release onedir
bash build_desktop.sh                    # sidecar + Tauri .deb/.appimage
```

## Key Rules

1. **Branch discipline** — feature branch -> PR -> CI green -> merge. No direct push to main.
2. **Conventional commits** — `type(scope): description`. Types: feat/fix/chore/docs/ci/refactor/release.
3. **No secrets in code** — API keys in `.env` only; `.env` is gitignored and never committed.
4. **Local-first** — every feature must work without network/API keys; cloud is opt-in.
5. **Timestamp provenance** — AI-generated claims carry `[mm:ss]` source timestamps.
6. **No untracked files at session end** — commit, gitignore, or delete before closing.

## Forbidden Actions

- Direct push to main.
- Committing `.env`, credentials, or API keys.
- Skipping git hooks (`--no-verify`).
- Adding external runtime dependencies without documenting in requirements.txt / package.json.
- Destructive git operations (force push, reset --hard) without explicit user approval.

## Directory Map

```
backend/           Python FastAPI sidecar (main.py entry)
backend/tests/     Backend unit tests (stdlib unittest)
backend/routers/   API route modules
backend/services/  Business logic services
frontend/          React + Vite app
frontend/src/      React source
frontend/src-tauri/ Tauri desktop shell (Rust)
frontend/tests/    Playwright E2E tests
scripts/           Build/release utilities
docs/              Architecture, design specs, guides, release notes
test/              Integration test fixtures
```

## Execution Protocol

- Global rules (commit format, stop conditions, stage reports): `~/.claude/CLAUDE.md`
- Current state cursor: `CURSOR.md` (read on every session start)
- Agent-specific commands: `AGENTS.md`

## Docs Retirement

- Docs unreferenced for 20+ days and not linked from GOVERNANCE.md or README.md: archive to `docs/history/`.
- Session end: no untracked files allowed — commit, gitignore, or delete.
