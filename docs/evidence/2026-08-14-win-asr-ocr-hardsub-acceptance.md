# Windows ASR/OCR hardsub-recovery — gap analysis + acceptance criteria

Status: pre-implementation gap analysis for **N04**. Nothing in this
document is marked done; every claim below is either a direct code citation
or a command I actually ran in this session (2026-08-14, branch
`win-asr-ocr-hardsub-recovery`, `b6bf33e`). No commit/push/PR was made.

Related: `docs/install/windows.md` (user-facing install doc, no ASR-runtime
mention), `backend/services/readiness.py`, `backend/ffmpeg_runtime.py`,
`.github/workflows/package.yml` (Windows packaging + smoke CI).

---

## 1. Fixture — location and how to build it

`test/fixtures/hardsub_no_cc/` (new; `test/` did not exist before this
session — `GOVERNANCE.md`'s directory map documents it but the directory
itself was missing, which is its own small spec-drift note).

- `make_fixture.sh <output.mp4>` — deterministic `ffmpeg` command producing
  a 6s/640x360 MP4, burned-in text `HARDSUB LINE ONE` (t=1-3s) / `HARDSUB
  LINE TWO` (t=3-5s), silent audio track, **zero subtitle streams**.
- `README.md` — rationale, regeneration command, and the verified expected
  OCR output.

**Reference video** (`https://youtu.be/OQ09v_T81I8`) — checked live this
session via `yt-dlp --skip-download`: public, 719s, `subtitles: []`,
`automatic_captions: []`. Genuinely no CC of any kind, so it's a faithful
real-world example of the case this feature exists for. It is **not**
wired into the fixture or any automated test:

- not reproducible/offline — depends on network + the video staying up,
  public, and unchanged;
- `bash backend/run_tests.sh` runs with no network (`GOVERNANCE.md`);
- committing downloaded YouTube video bytes into git is a redistribution
  problem this project doesn't need.

Instead, only the generator script is committed — the same pattern
`frontend/tests/ui/asr.spec.js:11-16` already uses (`ffmpeg -f lavfi ...
sine=...` synthesized in `test.beforeAll()`, never checked into git). The
real video stays useful only as a one-time **manual** sanity check (see
§3, criterion 4) — the branch name that scopes this whole task even comes
from a real captionless-hardsub video needing recovery, so a live check
against one has product value even though it can't be a CI dependency.

**End-to-end verification actually run this session** (not asserted from
reading code): generated the fixture, extracted the t=2s frame, and ran
the real `backend/local_ocr.py:extract_text()` against it —

```
OCR_RESULT: 'HARDSUBLINEONE'
```

RapidOCR drops spaces from spaced capitalized text; that's expected.
Assertions against this fixture should match substrings (`HARDSUB`,
`LINEONE`, `LINETWO`), not exact equality. Full transcript in
`test/fixtures/hardsub_no_cc/README.md`.

**Open question for N04**: the video-capture OCR lane only accepts a
YouTube URL end-to-end (`production_extractor.py` → `_download_lowres_video`
→ `canonicalize_youtube_url` → `yt_dlp`) — there is no local-file input.
That means an offline, fully-reproducible *Op-Demo* of "OCR reads a local
file's hardsub" isn't possible through the shipped UI as-is; either accept
a pinned real YouTube URL as a live-network exception for the manual
acceptance step only (not CI), or treat "local-file OCR input" as a
product gap to scope separately. Not resolved here — flagging for N04 to
decide, not picking silently.

---

## 2. Regression-test gap inventory

Confirmed by reading the actual call paths and the actual existing spec
files (not inferred from file names). Each item names the exact file/line
this session verified.

### Backend (`backend/tests/`, stdlib unittest, no network)

| # | Gap | Evidence |
|---|-----|----------|
| B1 | `ffmpeg_runtime.resolve()`'s fallback order (downloaded copy → env override → PATH) and the win-64 `.exe` suffix are untested. `test_ffmpeg_runtime.py` only covers `_download_and_extract`'s TLS context and sha256-mismatch discard — never calls `resolve()`. | `backend/ffmpeg_runtime.py:59-67`, `backend/tests/test_ffmpeg_runtime.py` (94 lines, no `resolve()` reference) |
| B2 | **[ASR runtime discovery]** No test pins that `video_audio_asr.transcribe_youtube_audio` → `_meeting_asr_local` raises, when whisper.cpp is absent, the literal message telling the user to run `setup_asr_runtime.sh`. Nothing catches a regression back to this message once it's fixed, and nothing today proves this is the exact string a packaged user sees on the video ASR button. | `backend/services/meetings.py:206-209`, reached from `backend/video_audio_asr.py:48-53` and `backend/routers/capture.py:433-440` |
| B3 | **[OCR sidecar failure]** `local_ocr.extract_text(data)` is called with no `try/except` inside the per-frame loop (`production_extractor.py:456-461`); an engine exception on one bad frame (not just the construction-time `LocalOcrUnavailable`, which *is* caught at line 380) propagates as an unhandled error with no assertion on partial results or that `tmp_root` still gets cleaned up. `test_local_ocr.py` only unit-tests `texts_from_result`'s pure normalization — no failure-mode test exists. | `backend/production_extractor.py:456-461`, `backend/tests/test_local_ocr.py` (22 lines) |
| B4 | **Confirmed Windows-breaking bug**, not hypothetical — reproduced this session: `CAPS["storage_root"] = "/tmp"` and `tempfile.mkdtemp(prefix="vaultwiki_yt_api_extract_", dir="/tmp")` hardcode a POSIX path. `tempfile.mkdtemp(dir=X)` does not create `X` — it only creates the random-suffixed leaf under an *existing* `X`. `C:\tmp` does not exist on a stock Windows machine, so this raises `FileNotFoundError` before a single frame is sampled, every time. Reproduced directly: `tempfile.mkdtemp(dir='/nonexistent_posix_root_demo')` → `FileNotFoundError`. No test exists for this at all. | `backend/production_extractor.py:30,398` |
| B5 | No test asserts that `run_production_extractor` never reaches `local_ocr`/`analyze_frame` when `allow_provider_ocr` is false/absent — today this is only implied by `_dry_run`'s error list (line 318-320), never asserted against actual non-execution of the OCR call. | `backend/production_extractor.py:369-381` |

### Frontend (`frontend/tests/ui/*.spec.js`, Playwright)

| # | Gap | Evidence |
|---|-----|----------|
| F1 | No test exercises `noCaptions` + `/app/ffmpeg/status` → `ready:false`. `capture.spec.js`'s only OCR test hardcodes `route('**/app/ffmpeg/status', ...ready:true)` — the not-ready → `installFfmpeg()` → poll → ready flow (`VideoCapture.jsx:45-58`) has zero coverage. | `frontend/tests/ui/capture.spec.js:75-77`, `frontend/src/features/capture/VideoCapture.jsx:34-58` |
| F2 | **[ASR runtime discovery]** `runVideoAsr()` / `POST /app/video-audio-asr` has **zero** E2E coverage. `asr.spec.js` only exercises the separate *meeting-audio* tier selector (`MeetingAudioTab`), never the video-lane ASR button. Needs both a success mock and a failure mock (the setup-script-style error) asserting the status line is actionable, not a raw dev-script name. | `frontend/tests/ui/asr.spec.js` (all 53 lines are meeting-audio, not video), `frontend/src/features/capture/VideoCapture.jsx:118-131` |
| F3 | **[OCR sidecar failure]** `capture.spec.js`'s only `production-extractor` mock is a 200 success (`ocr_text: '硬字幕第一句\n硬字幕第二句'`). No mock covers a 400/500 response or an empty `ocr_text` — the `OCR 失敗：...` branch (`VideoCapture.jsx:149`) is unexercised, and nothing asserts the draft/save flow doesn't half-proceed as if OCR had succeeded. | `frontend/tests/ui/capture.spec.js:78-81`, `frontend/src/features/capture/VideoCapture.jsx:132-150` |
| F4 | No test covers the cloud-OCR consent boundary named in the task (§3 criterion 5): with a mocked `OPENAI_API_KEY`-configured backend, does the UI say anything *before* the click that this specific run will upload frames, or only after (`已用雲端畫面 OCR...`, disclosed retroactively)? | `frontend/src/features/capture/VideoCapture.jsx:132-149`, `backend/production_extractor.py:372` |

### CI / packaging

| # | Gap | Evidence |
|---|-----|----------|
| C1 | No CI workflow provisions or checks the ASR runtime (whisper.cpp) on any platform — `package.yml` and `release.yml` build and smoke-test the sidecar's HTTP surface but never touch ASR readiness. `setup_asr_runtime.sh` (which requires `git cmake make cc g++ curl`) is referenced only from `docs/install/development.md` and `backend/services/meetings.py` — never from a packaging/release workflow. | `grep -rn whisper .github/workflows/` → no hits; `docs/install/development.md:67-72` |
| C2 | `scripts/smoke_bundled_sidecar.sh` (runs on `windows-latest` in CI today) checks `/api/health` for `"model_policy"` only — it doesn't assert the `production_extractor.tools.ffmpeg/ffprobe.available` block that's already in the same response. Cheap to add once B1 exists. | `scripts/smoke_bundled_sidecar.sh:37-40`, `backend/routers/readiness.py:352-361` |

---

## 3. Windows packaged acceptance criteria (for N04 to quote directly)

Each criterion states the check first (quotable as-is), then today's actual
status with citation. **PASS is not claimed for any item here** — this
section defines what N04 needs to make true and how to check it, mirroring
this repo's own `PASS`/`PARTIAL`/`BLOCKED` discipline.

**1. sidecar 可啟動且保持 healthy** — 封裝版 `.exe` 啟動後，`GET /api/health`
在啟動起算的有限時間內回傳 200 且 `ok:true`、`model_policy` 非空；閒置數分鐘後
再次呼叫仍回傳 200；過程中不應跳出額外主控台／終端機視窗。
　現況：啟動 + 單次 health 已由 `scripts/smoke_bundled_sidecar.sh` 在
`windows-latest` CI runner 上驗證（`.github/workflows/package.yml`
`smoke bundled sidecar` step）。**缺口**：沒有「跑一段時間後仍 healthy」的
持續性檢查（見 gap 表外此項，非既有清單編號，屬於 C1/C2 之外的新增建議）；
額外視窗問題 `docs/install/windows.md` 記載已修過一次，但沒有回歸測試釘住。

**2. ffmpeg/ffprobe 可發現** — `GET /api/health` 回傳的
`production_extractor.tools.ffmpeg.available` 與 `.tools.ffprobe.available`
皆為 `true`，且各自 `version` 欄位非空字串。首次啟動（尚未下載時）預期為
`false`；使用者點一次「下載媒體工具」後（`POST /app/ffmpeg/install` →
輪詢 `GET /app/ffmpeg/status`），兩者於有限時間內變為 `true`，全程不需使用者
自行安裝 ffmpeg。
　現況：探索路徑已存在且含 Windows（`ffmpeg_runtime.py` 的 `_REGISTRY`
含 `win-64`，sha256 pin），`/api/health` 已回報此欄位（gap 表 C2 指出尚未被
smoke test 斷言）。**缺口**：`resolve()` 本身無回歸測試（gap 表 B1）。

**3. ASR 不再要求 packaged user 手動執行 setup_asr_runtime.sh** —
封裝版使用者在無字幕影片點擊「下載音檔並轉錄（ASR）」時，錯誤訊息（若有）
不得提及 shell script 名稱或任何開發工具鏈指令（`git`/`cmake`/`make`/`cc`/
`g++`）；理想上應提供應用內一次性取得/建置 ASR runtime 的路徑（比照 ffmpeg
的 status/install 對）。
　現況：**目前不通過**。`_meeting_asr_local`（video ASR 走的正是這個函式）
在 whisper.cpp 缺席時丟出的訊息就是「請跑 setup_asr_runtime.sh」
（`backend/services/meetings.py:209`），而封裝流程從未產生過 whisper.cpp
（gap C1），前端也沒有任何對應 UI（不像 ffmpeg 有 `RuntimeSettings`/
`VideoCapture` 的 status＋install 呼叫）。這是本次盤點中最明確的
未通過項目。

**4. OCR 能取得硬字幕文字** — 針對本文件 §1 的 fixture（或等效無 CC
硬字幕影片），點擊「讀畫面硬字幕（OCR）」後於有限時間內回傳非空文字，且
內容包含畫面上的字（以本 fixture 為例：`HARDSUB`、`LINEONE`、
`LINETWO` 子字串），暫存影格清理完畢（`cleanup_verified:true`）。
　現況：OCR 引擎本身能力已驗證（本次實跑 `local_ocr.extract_text()`
對 fixture 回傳 `'HARDSUBLINEONE'`），但**目前會在 Windows 上於採樣任何
影格之前就先當掉**——`production_extractor.py:398` 的
`tempfile.mkdtemp(dir="/tmp")` 在 `/tmp`（Windows 上通常不存在）不存在時
拋 `FileNotFoundError`（gap B4，本次已機械重現）。此項判準要成立，
前提是先修掉這個硬編路徑。

**5. 不會未經同意上傳影片或切換付費 ASR** — 未設定雲端金鑰時，OCR／ASR
不得嘗試任何對外付費 API 呼叫；設定金鑰後，本次 session 第一次觸發雲端
OCR/ASR 前，畫面需在動作**之前**（不只是事後狀態列）明確標示「這將上傳畫面/
音訊到 <provider>」；未經該次確認，不得有影片/音訊位元組離開裝置。
　現況：**大部分已符合**——`ProductionExtractorReq` 預設
`user_authorized_media=False`／`allow_provider_ocr=False`（安全預設），
`_dry_run` 對兩者缺一即報錯（`production_extractor.py:318-320`），前端
只在「讀畫面硬字幕（OCR）」被實際點擊時才把三個旗標設 `true`
（`VideoCapture.jsx:138`）；影片 ASR 完全不會自動切雲端（`video_audio_asr.py`
沒有 mode 參數，只有本機路徑），會議 ASR 的雲端層是使用者另外點選的
獨立 tier（`services/meetings.py:284-289`，已有 `asr.spec.js` 的 tier-toggle
測試釘住）。**唯一具體缺口**：OCR 的本機/雲端選擇是依
`OPENAI_API_KEY` 是否存在自動決定（`production_extractor.py:372`），而非
點擊當下的獨立選擇——若使用者為了翻譯功能設過這把金鑰，點「讀畫面硬字幕
（OCR）」會靜默上傳影格到 OpenAI，畫面只在事後的狀態列才說明用了「雲端」
（`VideoCapture.jsx:147`）。是否要為此新增獨立同意步驟，留給 N04 判斷
（gap F4）。

**6. 不會在預覽確認前寫入筆記** — OCR/ASR 產生草稿內容後（無論成功或
中途失敗），「存入筆記」在使用者於畫面上檢視草稿並明確確認前必須維持
disabled／不可用；確認前 vault 中不得出現新建或被改動的 `.md` 檔，
即使 OCR/ASR 中途失敗也一樣。
　現況：**已符合，且已有回歸測試**——`AppStateRuntime.create_write_preview`
對空的/未審核的/被拒絕的 accepted_segment_ids 一律拒絕，且即使
segment 已 accepted，preview 仍固定回傳
`write_allowed:0`／`write_block_reason:"writeback_requires_separate_approval"`，
預覽當下不產生任何 `.md` 檔（`backend/tests/test_write_preview_guard.py`
全數斷言）；`capture.spec.js` 的草稿閘門測試另從 UI 角度釘住「存入筆記」
在草稿生成完成前維持 disabled。**小缺口**：兩邊測試都沒有專門用
OCR 產生（尤其是 OCR 失敗）的草稿去走一次這個閘門（見 F3）。

---

## 4. Review boundary

Working tree stayed on `win-asr-ocr-hardsub-recovery` at `b6bf33e`
throughout; no commit, push, PR, or merge was made. New files: this
document and `test/fixtures/hardsub_no_cc/{make_fixture.sh,README.md}` —
all currently untracked, left for the operator/N04 to review before
committing. Backend baseline re-confirmed green before writing this
report: `bash backend/run_tests.sh` → 338 tests, 1 skipped, exit 0.
