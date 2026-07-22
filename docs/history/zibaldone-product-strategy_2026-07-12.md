---
type: study
tags: [study/ai-tooling, study/product-strategy, topic/asr, topic/ocr, topic/llm-routing, topic/benchmark, project/zibaldone, project/portfolio]
status: historical
created: 2026-07-12
updated: 2026-07-21
canonical_source: ../architecture.md
superseded_by: ../architecture.md#zib-cli-001
summary: "歷史研究：競品速度來源、任務選型、優化槓桿、API-first 定位、benchmark 與 portfolio 主線；不再作為現行產品規格。"
---

# Historical archive: AI 工具策略：競品速度來源 × 多模型選型 × 定位/benchmark

> 2026-07-21 搬移自 Session Hub。這是歷史研究資料，不是現行產品規格。
> 現行產品與下一版設計以 [`docs/architecture.md`](../architecture.md) 為準。

## 起點問題

市面上類似 SaaS/開源（筆記摘要、價值提煉、OCR/ASR、會議音檔整理）處理**看起來更快**，關鍵技術是什麼？是大模型嗎？

## 核心結論：不是「大模型」，多半相反

速度來自 **更小/更專的模型 ＋ 專用推論硬體 ＋ 串流/平行架構**，不是更大的模型。

### 1. ASR（最大瓶頸）

- **蒸餾/turbo 版**：`whisper-large-v3-turbo`（809M，比 large 快 ~8x，品質幾乎不掉）、`distil-whisper`（~6x）。更小不是更大。
- **專用推論供應商**：Groq LPU 跑 whisper-turbo 數百倍實時；Deepgram Nova、AssemblyAI、Gladia、Speechmatics = 專門 ASR 引擎（非通用 LLM）、GPU 批次。
- **串流轉錄**：邊收邊轉，不等整檔。
- **VAD 切片**（Silero VAD）先去靜音再並行送。

### 2. LLM 摘要/重點

- **不用旗艦**：摘要不需要 frontier，競品多用 Flash / Haiku / mini 級（便宜快一個量級）。
- **極速推論**：Groq / Cerebras / SambaNova 每秒 500–2000+ token（一般 50–100）。
- **串流輸出**：token 即時吐，感知延遲 ≠ 實際總時長。
- **map-reduce 平行**：長逐字稿切塊 → 各塊並行摘要 → reduce，不是序列塞整篇。

### 3. OCR

- 硬字幕 competitors 多用**專用 OCR**（PaddleOCR / Tesseract / 雲端 Vision），毫秒級。
- frame-grab + LLM vision：準但每幀一次 LLM 呼叫，慢且貴 =「準確度換速度/成本」。
- 反直覺：硬字幕常常 **ASR 比 OCR 好**，除非燒錄字幕與語音不同語言（翻譯字幕）才需 OCR。

### 4. 架構（常被低估）

競品的「快」有一半是工程：**串流 + 平行 chunk + 伺服器 GPU（非使用者 CPU）+ 快取/預取**。同模型序列 vs 平行差好幾倍。

## 各任務選型表（curated，非即時 ML 路由）

| 任務 | 快又便宜（預設） | 品質優先 | 隱私/離線 |
|---|---|---|---|
| 翻譯 | DeepL / Google MT | LLM Flash 級（懂上下文、術語一致） | 內建 llama.cpp |
| ASR | Groq whisper-turbo / Deepgram | whisper-large-v3 / Gemini 原生音訊 | whisper.cpp |
| OCR | PaddleOCR / Tesseract | LLM-vision | 本機 Paddle/Tesseract |
| 摘要/報告 | Flash / Haiku / mini + 串流 | Claude（結構/長文）/ Gemini（大 context 便宜） | 內建 llama.cpp |

## 比「換模型」更大的優化槓桿

1. **能不做就不做**（最大槓桿）：優先用現成字幕/官方逐字稿（zibaldone 的 CC→ASR→OCR 梯即此思路），每步先問「有沒有現成的」。
2. **前處理 > 換模型**：ASR 前 VAD 去靜音（少算秒=少付錢）；OCR 只在字幕變動的幀做（去重），別逐幀。常省 50%+。
3. **cascade 兩段式**：便宜模型跑全部，只把難段升級強模型（可「這段用更好模型重跑」）。
4. **快取/去重**：content-hash 記憶逐字稿/翻譯/摘要，不重算。
5. **串流體感**：邊轉邊顯示、token 即時吐。
6. **輸出模式**：同逐字稿 → 多輸出模板（條列/主管摘要/Q&A/待辦），凸顯懂場景、近乎零成本。
7. **先估後跑**：擴成「此工具＝$X・Y秒；便宜選項＝$Z」讓使用者知情選擇。

## 產品定位（PM 視角）

- **護城河 = 適配層(curation)，不是模型**。模型誰都能 call；「替使用者選對工具並說明為什麼」才是價值。
- 預設要**有主見**（opinionated default per task），零設定就好用；再給「品質/速度/成本」三向切換 + 一句「為什麼推這個」+ 可覆寫。
- **別過度工程**：即時量測品質自動切換的 router 是研究級題目、CP 值低。策展好、可解釋、可覆寫的預設表 + 前處理，才是務實解。

## 我的立場（歷史記錄）

- **API-first、不用 Ollama**：付費用三大品牌（Anthropic / OpenAI / Google）。既然付費，就要**對標競品**。
- zibaldone 的內建 llama.cpp（2.4GB）在首次精靈**可跳過不下載**、直接完成設定 → local 是純選配，非強制，定位不矛盾。

## 「有目的性」：競品對標 + per-task benchmark

最能證明 PM 能力的不是 app 本身，而是**用自己付費 API 跑真數據的對標報告**：

| 任務 | 對標競品 | 量測指標 |
|---|---|---|
| 會議/音檔 | Granola、Otter、Fireflies、NotebookLM | WER、分段/講者品質、延遲、$/小時 |
| 筆記摘要 | Notion AI、Mem、Napkin、Readwise | 重點覆蓋率、幻覺率、延遲、$/篇 |
| 翻譯字幕 | DeepL、YouTube 內建 | 術語一致性、可讀性、$/千字 |
| 路由層 | 各家單模型 | 自動選對工具相對單模型省多少 $、快多少 |

最後一列＝護城河證據：不是「我有好模型」，是「我幫你在對的任務選對工具，省 X%、快 Y%」。有數字，敘事就立起來。

## Portfolio 主線（把「玩」變「作品集」）

note app / vault / harness / loop / session hub 不是散的，是一套**個人 AI 作業系統**：

```
擷取(note app) → 結構化記憶(vault) → 執行紀律(harness/session-hub) → 自動化(loop)
     捕捉            長期記憶             怎麼可靠地叫 AI 幹活        無人值守
```

每個子專案各證明一種能力：產品化、資料建模、agent 可靠性、自動化。

## OpenWiki 評估（歷史決策）

**結論：借鏡不取代。** OpenWiki 的 agent-readable progressive disclosure、local-first、Markdown、多 provider 與本機金鑰概念，已收斂到 Zibaldone 的 Agent Bridge v1；完整決策與邊界以 [`docs/design/agent_bridge_spec.md`](../design/agent_bridge_spec.md) 為準。

- Agent Bridge v1 已落地：vault → agent 可讀索引。
- OKF typed-concept、YAML relation schema 只保留為未來匯出／互通評估。
- connector 自動刷新不採用；不得加入 hidden watcher、cron、telemetry 或 cloud sync。

## UX 改版歷史

六頁圖示化改版，已寫回 React 並發版：cost、收錄、收件匣、筆記庫、退場、設定；側欄新 LOGO＝筆記本 Z；主題色沿用原生 brand。這是改版歷史，不是目前規格入口。

## 歷史版本註記

當時記錄曾以 v0.8.1 為基準；目前公開版本與現行 release evidence 已由 [`docs/architecture.md`](../architecture.md) 與 release 文件管理。不要以本檔的舊版本描述判定目前狀態。
