"""Request schemas（S4.1 batch 1，自 main.py 抽出；ownership map 170-492 段）。
純 Pydantic 定義＋主機路徑正規化欄位，無其他 runtime 依賴。其餘 schema 跟著各自
router 的批次走（見 docs/design/incremental_refactor_baseline.md）。"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from pydantic import AfterValidator, BaseModel, Field

from app_config import normalize_host_path

# 主機路徑欄位：Windows 打包版後端自動把 /mnt/<x>/ 翻回 <X>:\（反向亦然）
VaultPath = Annotated[str, AfterValidator(normalize_host_path)]


class FetchReq(BaseModel):
    url: str = Field(..., description="YouTube URL or 11-character video id")
    vault_path: VaultPath = ""
    subfolder: str = ""


class TranslateReq(BaseModel):
    text: str
    target: str = "zh-TW"
    progress_id: str = ""


class SaveReq(BaseModel):
    url: str
    video_id: str
    title: str
    channel: str = ""
    published: Optional[str] = None
    duration: Optional[str] = None
    thumbnail: Optional[str] = None
    transcript_en: str = ""
    transcript_zh: str = ""
    timestamped_en: str = ""
    manual_summary: str = ""
    ai_summary: Dict[str, Any] = {}
    ai_mode: str = "quick"
    save_mode: str = "create"
    languages: List[str] = []
    is_short: bool = False
    failure_class: str = ""
    extraction_sources: List[str] = []
    coverage_summary: str = ""
    dry_run: bool = False
    extra_tags: List[str] = []
    filename: Optional[str] = None
    vault_path: VaultPath = ""
    subfolder: Optional[str] = None


class EstimateReq(BaseModel):
    text: str
    mode: str = "quick"


class SummarizeReq(BaseModel):
    title: str = ""
    transcript_en: str = ""
    transcript_zh: str = ""
    mode: str = "quick"
    source_url: str = ""
    kind: str = "video"  # video | article（提示語措辭）


class ProviderAsrReq(BaseModel):
    filename: str = "audio.bin"
    media_base64: str
    media_mime: str = "audio/mpeg"
    task: str = "asr"
    mode: str = "dry_run"
    language: str = ""
    prompt: str = ""


class ProviderOcrReq(BaseModel):
    filename: str = "frame.png"
    image_base64: str
    image_mime: str = "image/png"
    mode: str = "dry_run"
    prompt: str = ""


class ProductionExtractorReq(BaseModel):
    url: str
    mode: str = "dry_run"
    sample_count: int = 6
    max_provider_calls: int = 6
    user_authorized_media: bool = False
    allow_provider_ocr: bool = False
    confirm_report_only: bool = False
    prompt: str = ""


class AppWorkspaceReq(BaseModel):
    workspace_root: str
    privacy_policy: str = "local_first_no_hidden_cloud_sync"
    retention_policy: str = "raw_media_temporary_by_default"


class AppStorageTargetReq(BaseModel):
    workspace_root: str
    workspace_id: str
    root_path: str
    adapter_type: str = "markdown_obsidian"
    permissions: str = "preview_required"
    write_mode: str = "preview_only"


class AppSourceReq(BaseModel):
    workspace_root: str
    workspace_id: str
    platform: str = "youtube"
    canonical_url: str
    canonical_id: str
    title: str = ""
    route_state: str = "source_ready"
    permission_state: str = "public_metadata_and_caption_only"
    evidence_segments: List[Dict[str, Any]] = Field(default_factory=list)


class SourceToNoteCostPreflightReq(BaseModel):
    transcript_chars: int
    per_job_cap_usd: float = 0.03


class ValueSignalsReq(BaseModel):
    summary: Dict[str, Any] = {}


class JobWorkerAdvanceReq(BaseModel):
    workspace_root: str
    job_id: str


class NoteRollbackExecuteReq(BaseModel):
    vault_root: VaultPath
    note_relpath: str
    expected_previous_hash: str
    confirm: bool = False


class MeetingNoteReq(BaseModel):
    audio_path: str
    vault_path: VaultPath = ""
    dry_run: bool = True
    asr_mode: str = "local"  # local=本地 whisper.cpp（免費/離線）| whisperx=VAD切片+字級對齊（吃長音檔）| cloud=雲端 provider ASR（tier 設定時由 tier 覆蓋）
    asr_model: str = "base"  # 模型大小：base=快/繁體 | medium=較準/較慢/簡體（轉繁後寫入）
    language: str = "zh"  # 預設強制中文：消除 auto 偵測誤判（殺 realtime 的同一雷）；非中文會議才放 "auto"
    tier: str = ""  # 品質分層 快/中/高品質→(mode,model)；空=用明傳 asr_mode/asr_model（向後相容）
    precise: bool = False  # 精準/長音檔開關＝whisperx（VAD 切片+字級對齊）；正交於 tier，只翻本地 tier
    review_only: bool = False  # true=停在可編輯草稿，不直接寫入
    template_id: str = "general"
    glossary: List[str] = Field(default_factory=list)


class ImportTranscriptReq(BaseModel):  # GLUE：匯入既有逐字稿（SRT/VTT/TXT/JSON），跳 ASR
    text: str = ""
    filename: str = ""
    vault_path: VaultPath = ""
    dry_run: bool = True
    review_only: bool = False
    template_id: str = "general"
    glossary: List[str] = Field(default_factory=list)


class MeetingDraftSaveReq(BaseModel):
    vault_path: VaultPath = ""
    audio_path: str = ""
    transcript: str
    summary: Dict[str, Any]
    job_id: str = ""


class MeetingAudioRepairReq(BaseModel):
    vault_path: VaultPath
    note_relpath: str
    audio_path: str


class AsrModelDownloadReq(BaseModel):
    model: str = "medium"


class OllamaPullReq(BaseModel):
    model: str = "gemma3:4b"


class SourceToNoteReq(BaseModel):
    url: str
    vault_path: VaultPath = ""
    subfolder: str = ""
    per_job_cap_usd: float = 0.03
    dry_run: bool = True
    save_mode: str = "create"


class NewsSourceToNoteReq(BaseModel):
    url: str
    title: str
    content: str = ""
    summary: str = ""
    source_type: str = ""
    vault_path: VaultPath = ""
    subfolder: str = ""
    dry_run: bool = True


class VaultNoteRollbackReq(BaseModel):
    vault_path: VaultPath
    subfolder: str = "note_study/02_Sources/youtube"
    video_id: str
    expected_previous_hash: str
    confirm: bool = False


class AppIntakeUrlReq(BaseModel):
    workspace_root: str
    workspace_id: str
    url: str
    operator_intent: str = "create_transcript_note"
    source_input_mode: str = "single_url"
    route_preference: str = "lowest_risk_caption_first"
    dry_run: bool = True
    idempotency_key: str = ""


class AppCaptionProbeReq(BaseModel):
    workspace_root: str
    workspace_id: str
    source_id: str
    canonical_url: str = ""
    canonical_id: str = ""
    platform: str = "youtube"
    route_preference: str = "native_caption_first"
    caption_languages: List[str] = Field(
        default_factory=lambda: ["zh-TW", "zh-Hant", "zh", "en", "en-US", "en-GB"]
    )
    dry_run: bool = True
    idempotency_key: str = ""


class AppNativeCaptionApiProbeReq(BaseModel):
    workspace_root: str
    workspace_id: str
    source_id: str
    canonical_url: str = ""
    canonical_id: str = ""
    platform: str = "youtube"
    caption_languages: List[str] = Field(
        default_factory=lambda: ["zh-TW", "zh-Hant", "zh", "en", "en-US", "en-GB"]
    )
    allow_ytdlp_fallback: bool = False
    allow_media_download: bool = False
    allow_credential_read: bool = False
    persist_evidence: bool = False
    idempotency_key: str = ""


class AppYtdlpSubtitleFallbackProbeReq(BaseModel):
    workspace_root: str
    workspace_id: str
    source_id: str
    canonical_url: str = ""
    canonical_id: str = ""
    platform: str = "youtube"
    caption_languages: List[str] = Field(
        default_factory=lambda: ["zh-TW", "zh-Hant", "zh", "en", "en-US", "en-GB"]
    )
    triggering_operator_state: str = "native_caption_unavailable_review_required"
    allow_ytdlp_subtitle_fallback: bool = True
    allow_media_download: bool = False
    allow_credential_read: bool = False
    persist_evidence: bool = False
    idempotency_key: str = ""


class AppLocalAsrReportOnlyProbeReq(BaseModel):
    workspace_root: str
    workspace_id: str
    source_id: str
    canonical_url: str = ""
    canonical_id: str = ""
    platform: str = "youtube"
    triggering_operator_state: str = "ytdlp_subtitle_unavailable_review_required"
    allow_media_download: bool = True
    allow_local_asr: bool = True
    allow_credential_read: bool = False
    persist_evidence: bool = False
    max_sample_seconds: int = 30
    max_download_bytes: int = 10_000_000
    idempotency_key: str = ""


class AppRouteReq(BaseModel):
    workspace_root: str
    source_id: str
    route_state: str = "native_caption_available"
    stage: str = "route_decision"


class AppEvidenceReq(BaseModel):
    workspace_root: str
    source_id: str


class AppReviewReq(BaseModel):
    workspace_root: str
    segment_id: str
    decision: str = "accepted"
    reviewer_note: str = ""


class AppWritePreviewReq(BaseModel):
    workspace_root: str
    source_id: str
    target_id: str
    accepted_segment_ids: List[str]
    template_id: str = "personal_learning_note_v1"


class AppWriteNoteReq(BaseModel):
    workspace_root: str
    preview_id: str
    target_note_path: str
    previous_hash: str
    idempotency_key: str
    index_path: str = ""
    dry_run: bool = True


class AppRollbackReq(BaseModel):
    workspace_root: str
    note_id: str
    previous_hash: str
    rollback_action: str = "restore_previous_note_hash"
    action_status: str = "available_if_future_write_occurs"
