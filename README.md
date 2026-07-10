# Zibaldone

> *zibaldone* (n., Italian) — "a heap of things"; a notebook where everything goes.
> Giacomo Leopardi kept one for 4,500 pages. This one is an app.

Zibaldone turns **YouTube videos, web articles, and meeting audio** into structured,
timestamped notes — written straight into your own Markdown vault (Obsidian-compatible).
Local-first, works **without any API key**, and every AI-generated claim carries a
`[mm:ss]` timestamp you can click to verify against the source.

**繁體中文使用者：** UI 為繁體中文——這是作者日常使用的真實產品，不是 demo。

![Paste a YouTube URL, review free captions, generate an AI draft with a local model, save into your vault](docs/assets/demo-hero.gif)

*Real recording: free captions → built-in local model (llama.cpp `gemma-3-4b-it`) draft → note saved to the vault. Total cloud cost: $0.*

## Why it exists

Most "AI note" tools are thin wrappers around one cloud API. Zibaldone is built the
other way around:

- **Your vault is the product.** Notes land as plain Markdown files in a folder you
  choose. Uninstalling the app leaves your notes byte-identical.
- **No-key ladder.** Everything works without a paid API key: YouTube captions,
  local Whisper ASR (3 quality tiers), and local LLM translate/summarize via a
  built-in llama.cpp runtime downloaded on first use (~15 MB engine + a ~2.4 GB
  model). Cloud models are an opt-in upgrade, not a requirement.
- **Timestamp attribution.** Summaries, action items, and decisions each carry a
  `[mm:ss]` anchor back to the transcript. If a claim can't be attributed, it is
  dropped rather than invented.
- **Honest engineering.** 76 API endpoints locked by a surface-contract test,
  320+ backend tests, 21 Playwright E2E cases, release gated on CI, and a size
  budget that fails the build past 110 MB.

## Feature map

| Lane | Input | Output |
|------|-------|--------|
| Video | YouTube URL | Captions (or ASR) → translated, structured note with clickable timestamps |
| Article | Web URL / PDF | Readable extraction → summarized note with source link |
| Meeting | Local audio file | 3-tier local/cloud ASR → timestamped minutes (decisions, action items, quotes) |

Plus: full-text vault search, a news-source radar that auto-drafts into an intake
inbox with a retirement flow, per-model cost tracking (local models report $0), and
an in-app updater.

![Drop a meeting audio file, watch the local ASR job, get minutes where every action item carries a clickable timestamp](docs/assets/demo-meeting.gif)

*Meeting lane: local Whisper ASR → reviewable draft → every action item and decision
anchored with a `[mm:ss]` capsule that seeks the audio player.*

## Model routes (the no-key ladder)

1. **Built-in local runtime** — the keyless default. The first-run wizard downloads a
   bundled [llama.cpp](https://github.com/ggml-org/llama.cpp) server (pinned release,
   checksummed) plus a quantized `gemma-3-4b-it` model on first use, so a clean
   machine gets offline translate/summarize with no API key. Once installed it is the
   default `translate` model; cloud stays the fallback.
2. **Subscription CLIs** *(off by default)* — detects logged-in `claude` / `codex` /
   `gemini` CLIs and can route translate/summarize through your existing subscription
   at zero app-side cost. Disabled unless you explicitly enable it in Settings
   (calling vendor CLIs programmatically may sit in a gray zone of their terms — read
   them first).
3. **Cloud APIs** — OpenAI / Anthropic / Google keys, stored locally, never logged,
   with per-job and daily cost caps enforced server-side.

## Install

Grab the installer from [Releases](https://github.com/justinyu73/zibaldone/releases):
Windows NSIS installer or macOS DMG (Apple Silicon).

This project deliberately ships **without** paid code-signing:

- **macOS** shows *"Zibaldone is damaged"* on first launch (that's Gatekeeper's
  wording for *unsigned*, not actual damage). After verifying your download came
  from this repo's Releases: `xattr -r -d com.apple.quarantine "/Applications/Zibaldone.app"`
- **Windows** SmartScreen: "More info" → "Run anyway".

See [docs/install/](docs/install/) for full platform guides and troubleshooting.

## Architecture (5-minute tour)

```text
┌────────────┐   invoke/HTTP    ┌──────────────────┐   spawn+reap   ┌───────────────┐
│ React UI   │ ───────────────▶ │ Tauri shell (Rust)│ ─────────────▶ │ FastAPI sidecar│
│ (webview)  │ ◀─────────────── │ session token,    │                │ (PyInstaller)  │
└────────────┘    per-launch    │ updater, lifecycle│                └───────┬───────┘
                  bearer token  └──────────────────┘                        │
                                                                    routers/ services/
                                                                    ├─ capture  (YT/article)
                                                                    ├─ meetings (ASR+distill)
                                                                    ├─ library  (vault/search)
                                                                    ├─ settings (models/cost)
                                                                    └─ readiness (probes)
```

Highlights worth reading the code for:

- **Sidecar lifecycle** ([`lib.rs`](frontend/src-tauri/src/lib.rs)): orphan reaping is
  two-layered — a recorded-PID reap plus a name-verified port sweep, because a
  force-quit orphan squatting the fixed port with a stale session token makes every
  request 401 and looks exactly like a broken install. Found on a real machine;
  fixed with a regression test.
- **Onedir cold start** ([`lib.rs`](frontend/src-tauri/src/lib.rs), [`release.yml`](.github/workflows/release.yml)):
  the sidecar ships as a PyInstaller `--onedir` tree bundled as a Tauri resource, not
  a `--onefile` binary that re-extracts ~200 MB to a temp dir on every launch —
  cutting spawn → `/api/health` from ~1.3 s to ~0.6 s. Release spawns the inner
  executable directly; dev keeps the source-backed shell sidecar.
- **API surface contract** ([`test_api_surface_contract.py`](backend/tests/test_api_surface_contract.py)):
  all 76 method/path pairs are pinned; refactors that add, drop, or rename an
  endpoint fail immediately.
- **Provider abstraction** ([`providers.py`](backend/providers.py)): one
  `chat_complete()` across OpenAI/Anthropic/Google/built-in llama.cpp/CLI, with
  keyless routes short-circuiting the key check and JSON output hard-normalized
  downstream (never trust a model to follow format instructions).

Full write-up: [docs/architecture.md](docs/architecture.md).

## Development

```bash
# backend
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover tests        # 320+ tests

# frontend
cd frontend && npm ci
npx vitest run src/ && npx vite build
npx playwright test                                 # 21 E2E cases (spawns real backend)

# desktop shell
cd frontend/src-tauri && cargo test --lib
```

CI runs the same suites plus a product-readiness check (source size, forbidden
paths, version shape, release artifact budget) on every push.

## Scope & support

This is a **portfolio-grade personal product**: one maintainer, best-effort support,
no SLA. Issues and PRs are welcome but triage is not guaranteed — see
[CONTRIBUTING.md](CONTRIBUTING.md). Security reports: see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
