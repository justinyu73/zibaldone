# Zibaldone

> *zibaldone* (n., Italian) — "a heap of things"; a notebook where everything goes.
> Giacomo Leopardi kept one for 4,500 pages. This one is an app.

Zibaldone turns **YouTube videos, web articles, and meeting audio** into structured,
timestamped notes — written straight into your own Markdown vault (Obsidian-compatible).
Local-first, works **without any API key**, and every AI-generated claim carries a
`[mm:ss]` timestamp you can click to verify against the source.

**繁體中文使用者：** UI 為繁體中文——這是作者日常使用的真實產品，不是 demo。

![Paste a YouTube URL, review free captions, generate an AI draft with a keyless model, save into your vault](docs/assets/demo-hero.gif)

*Real recording: free captions → draft via a logged-in subscription CLI (`codex`, $0 app-side cost) → note saved to the vault. Total cloud cost: $0. (Built-in llama.cpp works the same keyless way.)*

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
  320+ backend tests, 27 Playwright E2E cases, release gated on CI, and a size
  budget that fails Windows artifacts past 110 MB and macOS artifacts past 200 MB.

## Feature map

| Lane | Input | Output |
|------|-------|--------|
| Video | YouTube URL | Captions (or ASR) → translated, structured note with clickable timestamps |
| Article | Web URL / PDF | Readable extraction → summarized note with source link |
| Meeting | Local audio file | 3-tier local/cloud ASR → timestamped minutes (decisions, action items, quotes) |

Plus: full-text vault search, a news-source radar that auto-drafts into an intake
inbox with a retirement flow, an on-demand local Agent Bridge index for coding and
research agents, per-model cost tracking (local models report $0), and an in-app
updater.

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

## 安裝與下載

最新公開版請到 [GitHub Releases](https://github.com/justinyu73/zibaldone/releases)。
Release 會提供：

- **Windows x64**：`Zibaldone_<版本>_x64-setup.exe`
- **macOS Apple Silicon**：`Zibaldone_<版本>_aarch64.dmg`
- updater 簽章檔與 `SHA256SUMS-*.txt`：用來核對下載完整性；不要把 `.sig` 當成安裝檔。

Windows/macOS 安裝檔是 GitHub Actions 在對應原生 runner 建置的公開版本，
一般使用不需要 WSL、Python、Node 或手動啟動 FastAPI。Intel Mac 目前沒有公開
安裝檔；Linux 目前請依開發文件自行建置。

### 安裝前的風險與信任邊界

這是開源、未購買商業憑證的個人產品：

- Windows 沒有 Microsoft Authenticode 憑證，SmartScreen 可能顯示未知發行者。
- macOS 沒有 Apple Developer ID notarization，Gatekeeper 可能顯示「App 已損毀，無法打開」；這通常是隔離標記，不代表檔案真的損壞。
- 只有在確認網址是本 repo 的 GitHub Release、版本與 `SHA256SUMS-*.txt` 相符後，才依平台指南處理警告；不要關閉整台電腦的防毒、SmartScreen 或 Gatekeeper，也不要執行廣泛的 quarantine 移除指令。
- App 會依你明確操作連線 YouTube、文章網址、GitHub Release、可選的雲端 AI provider；筆記庫留在你選擇的本機路徑。詳見 [隱私與網路行為](docs/privacy-and-network.md)。

### 第一次使用

1. 安裝後在首次設定選擇筆記庫根目錄；這個資料夾是你的外部 Markdown 資料，不會因解除安裝而刪除。
2. 第 4 步的 **內建本機 AI** 是 llama.cpp + Gemma，不是 Ollama，也不是 CLI；可選「跳過，本次不下載」並完成設定，之後再到設定下載。
3. 若要使用 Claude／Codex／Gemini 訂閱 CLI，到設定勾選「顯示訂閱 CLI 模型」後，**一定要再按「儲存模型/上限」才會生效**。
4. 先用預覽、字幕／ASR／OCR 與可編輯草稿確認內容，再按「存入筆記」。沒有設定筆記庫根目錄時，草稿仍可產生，但不能寫入。

完整指南：[安裝文件索引](docs/install/README.md)、[Windows](docs/install/windows.md)、[macOS](docs/install/macos.md)、[開發環境](docs/install/development.md)。

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
