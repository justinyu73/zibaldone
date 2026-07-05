"""語音 lane 後端契約測試（本地 whisper 接進既有 meeting-note orchestrator）.

stdlib unittest，無 provider/network/credential。preflight 用真 ffmpeg（缺則跳過）；
本地 whisper 走 runtime-gated 分支 + JSON 解析單元；有 runtime 的機器(JY 本機)真跑轉錄。
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import routers.meetings as R  # noqa: E402
import services.meetings as M  # noqa: E402
import whisper_transcribe as W  # noqa: E402
from audio_preflight import audio_preflight  # noqa: E402
from fastapi import HTTPException  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
_JFK = Path.home() / ".config/yt-note-app/tools/_whisper_src/samples/jfk.wav"
_RUNTIME_READY = M._local_asr_runtime_readiness().get("runtime_ready") is True


def _make_wav(path: Path, *, seconds: float, kind: str) -> None:
    src = "anullsrc=r=16000:cl=mono" if kind == "silence" else "sine=frequency=440:sample_rate=16000"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", src, "-t", str(seconds),
         "-ac", "1", "-ar", "16000", path.as_posix()],
        capture_output=True, check=True,
    )


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not available")
class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vi-audio-pf-"))

    def test_usable_tone(self):
        wav = self.tmp / "tone.wav"
        _make_wav(wav, seconds=2.0, kind="tone")
        result = audio_preflight(wav.as_posix())
        self.assertTrue(result["ok"])
        self.assertTrue(result["usable"])
        self.assertGreaterEqual(result["duration_seconds"], 1.5)
        self.assertEqual(result["sample_rate"], 16000)

    def test_silence_not_usable(self):
        wav = self.tmp / "silent.wav"
        _make_wav(wav, seconds=2.0, kind="silence")
        result = audio_preflight(wav.as_posix())
        self.assertTrue(result["ok"])
        self.assertFalse(result["usable"])
        self.assertIn("靜音", result["reason"])

    def test_missing_file(self):
        result = audio_preflight((self.tmp / "nope.wav").as_posix())
        self.assertFalse(result["ok"])
        self.assertFalse(result["usable"])


class WhisperParseTests(unittest.TestCase):
    def test_parse_offsets_to_segments(self):
        data = {"transcription": [
            {"offsets": {"from": 0, "to": 1500}, "text": " 你好"},
            {"offsets": {"from": 1500, "to": 3200}, "text": "世界 "},
            {"offsets": {"from": 3200, "to": 3300}, "text": "  "},
        ]}
        segs = W._parse_whisper_json(data)
        self.assertEqual(len(segs), 2)  # 空白段丟棄
        self.assertEqual(segs[0], {"start": 0.0, "end": 1.5, "text": "你好"})

    def test_transcribe_runtime_gated_when_binary_missing(self):
        result = W.transcribe(
            "/nonexistent/audio.wav",
            binary_path="/nonexistent/whisper-cli", model_path="/nonexistent/model.bin",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "audio_not_found")

    def test_local_asr_fn_raises_when_runtime_not_ready(self):
        # Deterministic regardless of this machine's build: empty ASR root → not-ready.
        empty = tempfile.mkdtemp(prefix="vi-no-asr-")
        with mock.patch.dict(os.environ, {"YT_NOTE_ASR_ROOT": empty}):
            with self.assertRaises(ValueError):
                M._meeting_asr_local(Path("/tmp/x.wav"))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not available")
class MeetingNoteDryRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vi-meet-"))

    def test_dry_run_includes_preflight_verdict(self):
        wav = self.tmp / "talk.wav"
        _make_wav(wav, seconds=2.0, kind="tone")
        result = R.app_state_meeting_note(R.MeetingNoteReq(
            audio_path=wav.as_posix(), vault_path=self.tmp.as_posix(), dry_run=True,
        ))
        self.assertTrue(result["dry_run"])
        self.assertIsNotNone(result["preflight"])
        self.assertTrue(result["preflight"]["usable"])
        self.assertEqual(result["preflight"]["sample_rate"], 16000)

    def test_dry_run_missing_audio_intake_blocked(self):
        result = R.app_state_meeting_note(R.MeetingNoteReq(
            audio_path=(self.tmp / "nope.wav").as_posix(), vault_path=self.tmp.as_posix(), dry_run=True,
        ))
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "audio_file_not_found")


@unittest.skipUnless(_RUNTIME_READY and _JFK.is_file(), "whisper runtime or jfk sample not present")
class EndToEndRealLocalAsrTests(unittest.TestCase):
    """有 whisper runtime 的機器(JY 本機)真跑本地轉錄；CI 無 runtime 自動 skip。
    只驗本地 ASR 段（不碰 LLM summarizer，避免 credential/network）。"""

    def test_local_asr_real_transcribe(self):
        text = M._meeting_asr_local(_JFK, "en")
        self.assertIn("country", text.lower())


class LocalAsrModelResolveTests(unittest.TestCase):
    """base 用 runtime-lock 的模型；medium 用同目錄較大模型，缺檔則明確報錯（不靜默退回）。"""

    def test_base_uses_readiness_model_path(self):
        readiness = {"model": {"path": "/x/ggml-base.bin"}}
        self.assertEqual(M._resolve_local_asr_model("base", readiness), "/x/ggml-base.bin")
        self.assertEqual(M._resolve_local_asr_model("unknown", readiness), "/x/ggml-base.bin")

    def test_medium_requires_installed_model(self):
        tmp = Path(tempfile.mkdtemp(prefix="vi-asr-model-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "tools/whisper.cpp/models").mkdir(parents=True)
        with mock.patch.object(M, "_asr_root", return_value=tmp):
            with self.assertRaises(ValueError):  # not downloaded yet
                M._resolve_local_asr_model("medium", {"model": {"path": "/x/ggml-base.bin"}})
            (tmp / "tools/whisper.cpp/models/ggml-medium.bin").write_bytes(b"x")
            self.assertTrue(
                M._resolve_local_asr_model("medium", {}).endswith("ggml-medium.bin")
            )


class TimestampedTranscriptTests(unittest.TestCase):
    """quote+timestamp distill：每段前綴 [mm:ss] + 統一繁體；無 segments 退回純文字。"""

    def test_segments_get_mmss_prefix_and_traditional(self):
        out = M._timestamped_transcript([
            {"start": 0, "text": "各位早"},
            {"start": 73.4, "text": "结论"},  # 简体 → 應轉繁
        ])
        self.assertEqual(out.splitlines(), ["[00:00] 各位早", "[01:13] 結論"])

    def test_fallback_to_text_when_no_segments(self):
        self.assertEqual(M._timestamped_transcript([], "纯文字"), "純文字")

    def test_null_start_omits_prefix_no_fake_zero(self):
        # 雲端 gpt-4o-transcribe 不回時間戳（start=None）→ 不杜撰 [00:00]，純文字交摘要層略過
        out = M._timestamped_transcript([
            {"start": None, "text": "决议锁定中文"},
            {"start": 11.0, "text": "下一步"},
        ])
        self.assertEqual(out.splitlines(), ["決議鎖定中文", "[00:11] 下一步"])

    def test_single_segment_strips_fake_zero(self):
        # 雲端 whisper-1 偶把整段會議回成單一 start=0 segment（高品質 [00:00] bug 源頭）
        # → 視為無逐句時間戳、不前綴假 [00:00]（否則摘要全歸 00:00、點了跳 0:00 無意義）。
        out = M._timestamped_transcript([{"start": 0, "text": "整段會議內容都在這一段"}])
        self.assertEqual(out, "整段會議內容都在這一段")
        self.assertFalse(M._has_granular_timestamps([{"start": 0, "text": "x"}]))
        self.assertTrue(M._has_granular_timestamps([{"start": 0, "text": "a"}, {"start": 6, "text": "b"}]))


class QuoteTimestampDistillTests(unittest.TestCase):
    """quote+timestamp distill（form A 行內錨，spec docs/design/quote_timestamp_distill_spec.md）：
    LLM 真附 [mm:ss] 只能 Op-Demo 驗（需 provider）；no-spend 測鎖兩件機械保證——
    AC1 prompt 含時間戳歸因指令（regression guard）、離散項帶 [mm:ss] 無損渲染進 note。"""

    def test_prompt_requires_timestamp_attribution(self):
        p = M._MEETING_PROMPT
        self.assertIn("[mm:ss]", p)
        self.assertIn("action_items", p)
        self.assertIn("decisions", p)
        self.assertIn("略過", p)  # Q1：無法歸因 → 略過、不杜撰

    def test_timestamped_items_render_into_note(self):
        from meeting_note import build_meeting_markdown
        summary = {
            "title": "t", "summary": "s", "key_organization": "脈絡 [03:10]",
            "core_value": "省成本 [05:12]",
            "action_items": ["JY 測對齊準度 [21:40]"],
            "decisions": ["採 WhisperX CPU int8 [12:30]"],
            "attendees": [], "agenda": [],
        }
        md = build_meeting_markdown(summary, "[00:00] x", "/tmp/a.m4a", today="2026-06-24")
        self.assertIn("- JY 測對齊準度 [21:40]", md)
        self.assertIn("- 採 WhisperX CPU int8 [12:30]", md)
        self.assertIn("省成本 [05:12]", md)

    def test_summary_output_forced_traditional(self):
        # 小摘要模型偶發吐簡體（逐字稿已轉繁但 LLM 輸出軟約束）→ 硬保證收口繁體。
        simp = {"title": "会议笔迹优先级", "summary": "讨论质量与优先级 [05:12]",
                "action_items": ["补测试 [00:45]"], "decisions": ["采用本地为主"],
                "key_organization": "", "core_value": "", "attendees": [], "agenda": []}
        out = M._traditionalize_summary(simp)
        self.assertEqual(out["title"], "會議筆跡優先順序")   # s2twp 台灣用語：优先级→優先順序
        self.assertIn("討論", out["summary"])
        self.assertIn("[05:12]", out["summary"])           # 時間戳不受影響
        self.assertEqual(out["action_items"], ["補測試 [00:45]"])
        self.assertIn("採用", out["decisions"][0])


class MeetingAudioProvenanceTests(unittest.TestCase):
    """音檔出處（spec docs/design/meeting_audio_provenance_spec.md）：note 純文字、不嵌音檔，
    但 frontmatter 留 audio_source(檔名)+audio_path(全路徑)、body 有可見「## 音檔來源」連結。"""

    def test_provenance_link_and_path_in_note(self):
        from meeting_note import build_meeting_markdown
        summary = {"title": "t", "summary": "s", "key_organization": "", "core_value": "",
                   "action_items": [], "decisions": [], "attendees": [], "agenda": []}
        md = build_meeting_markdown(summary, "[00:00] x", "/home/user/meetings/2026 sync.m4a",
                                    today="2026-06-25")
        self.assertIn("audio_source: 2026 sync.m4a", md)            # 既有欄位保留（向後相容）
        self.assertIn("audio_path: /home/user/meetings/2026 sync.m4a", md)  # 新增全路徑
        self.assertIn("## 音檔來源", md)
        self.assertIn("[2026 sync.m4a](file:///home/user/meetings/2026%20sync.m4a)", md)  # 空白 quote
        self.assertIn("位置：/home/user/meetings/", md)

    def test_metadata_and_repair_preserve_note_body(self):
        from meeting_note import build_meeting_markdown, meeting_note_metadata, replace_meeting_audio_provenance
        with tempfile.TemporaryDirectory() as td:
            old = Path(td) / "old.mp3"
            new = Path(td) / "renamed meeting.mp3"
            old.write_bytes(b"old")
            new.write_bytes(b"new")
            summary = {"title": "t", "summary": "人工摘要", "key_organization": "", "core_value": "",
                       "action_items": [], "decisions": [], "attendees": [], "agenda": []}
            original = build_meeting_markdown(summary, "[00:11] 人工逐字稿", str(old), today="2026-07-01")
            repaired = replace_meeting_audio_provenance(original, str(new))
            meta = meeting_note_metadata(repaired)
            self.assertTrue(meta["is_meeting"])
            self.assertTrue(meta["audio_exists"])
            self.assertEqual(meta["audio_path"], str(new))
            self.assertEqual(meta["timestamps"], ["00:11"])
            self.assertIn("人工摘要", repaired)
            self.assertIn("人工逐字稿", repaired)
            self.assertIn("renamed%20meeting.mp3", repaired)


class MeetingJobCheckpointTests(unittest.TestCase):
    """job lifecycle 核心（spec docs/design/meeting_job_lifecycle_spec.md）：transcript
    checkpoint 後 retry 跳過 ASR——不重跑那段最貴的轉錄（n=1 最痛缺口）。"""

    def _audio(self, td):
        p = Path(td) / "a.wav"
        p.write_bytes(b"x" * 16)
        return str(p)

    def test_given_transcript_skips_asr(self):
        from meeting_note import run_meeting_note
        calls = {"asr": 0}
        with tempfile.TemporaryDirectory() as td:
            r = run_meeting_note(
                self._audio(td),
                asr_fn=lambda p: calls.__setitem__("asr", calls["asr"] + 1) or "[00:00] x",
                summarizer_fn=lambda t: {"title": "t", "decisions": []},
                writer_fn=lambda d: {"ok": True, "relative_path": "x.md"},
                dry_run=False, transcript="[00:00] cached")
        self.assertEqual(calls["asr"], 0)          # transcript 已給 → ASR 不被呼叫
        self.assertEqual(r["stage"], "written")

    def test_review_only_returns_editable_draft_without_writer(self):
        from meeting_note import run_meeting_note
        writes = []
        with tempfile.TemporaryDirectory() as td:
            r = run_meeting_note(
                self._audio(td),
                asr_fn=lambda p: "[00:00] 原始逐字稿",
                summarizer_fn=lambda t: {"title": "草稿", "summary": "摘要", "decisions": []},
                writer_fn=lambda data: writes.append(data),
                dry_run=False,
                review_only=True,
            )
        self.assertEqual(r["stage"], "review_ready")
        self.assertEqual(r["transcript"], "[00:00] 原始逐字稿")
        self.assertEqual(writes, [])

    def test_template_and_glossary_prompt_are_bounded(self):
        prompt = M._meeting_prompt("decision", ["YT Note App", "YT Note App", "WhisperX"])
        self.assertIn("決策會議", prompt)
        self.assertEqual(prompt.count("YT Note App"), 1)
        self.assertIn("WhisperX", prompt)

    def test_checkpoint_then_retry_does_not_rerun_asr(self):
        from meeting_note import run_meeting_note
        calls = {"asr": 0}
        saved = {}
        boom = {"first": True}

        def asr(p):
            calls["asr"] += 1
            return "[00:00] real transcript"

        def summ(t):
            if boom["first"]:
                boom["first"] = False
                raise ValueError("LLM down")
            return {"title": "t", "decisions": []}

        with tempfile.TemporaryDirectory() as td:
            audio = self._audio(td)
            # 第一次：ASR 成功 → on_transcript checkpoint → summarize 炸
            with self.assertRaises(ValueError):
                run_meeting_note(audio, asr_fn=asr, summarizer_fn=summ,
                                 writer_fn=lambda d: {"ok": True}, dry_run=False,
                                 on_transcript=lambda t: saved.__setitem__("t", t))
            self.assertEqual(calls["asr"], 1)
            self.assertEqual(saved["t"], "[00:00] real transcript")
            # retry：帶 checkpoint 的 transcript → ASR 不再被呼叫
            r = run_meeting_note(audio, asr_fn=asr, summarizer_fn=summ,
                                 writer_fn=lambda d: {"ok": True, "relative_path": "x.md"},
                                 dry_run=False, transcript=saved["t"])
        self.assertEqual(calls["asr"], 1)          # 仍是 1 ＝ retry 沒重跑 ASR
        self.assertEqual(r["stage"], "written")

    def test_checkpoint_key_is_content_addressed(self):
        # 修 footgun：checkpoint 以音檔內容(路徑+size+mtime+引擎)為 key、非 job_id，故同一個檔
        # 不管按「轉錄並存入」或「重試」、不管 job_id，都不重轉錄；換引擎或檔變才重轉。
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.wav"
            a.write_bytes(b"x" * 100)
            k1 = M._meeting_checkpoint_key(str(a), "local", "base")
            self.assertEqual(k1, M._meeting_checkpoint_key(str(a), "local", "base"))   # 同檔同引擎→同 key
            self.assertNotEqual(k1, M._meeting_checkpoint_key(str(a), "whisperx", "base"))  # 換引擎→重轉
            a.write_bytes(b"y" * 200)
            self.assertNotEqual(k1, M._meeting_checkpoint_key(str(a), "local", "base"))  # 檔變→重轉

    def test_checkpoint_key_includes_language_and_real_provider_model(self):
        with tempfile.TemporaryDirectory() as td:
            audio = self._audio(td)
            base = M._meeting_checkpoint_key(
                audio, "cloud", "base", language="zh", provider_model="whisper-1")
            self.assertNotEqual(base, M._meeting_checkpoint_key(
                audio, "cloud", "base", language="en", provider_model="whisper-1"))
            self.assertNotEqual(base, M._meeting_checkpoint_key(
                audio, "cloud", "base", language="zh", provider_model="gpt-4o-transcribe"))


class WhisperxTranscribeContractTests(unittest.TestCase):
    """whisperx_transcribe：缺檔在 import torch 前就返回（gate 不被重模型拖慢）。
    真實轉錄走 CPU 約 2.5× realtime，不進 gate；以 e2e 手動驗（scratchpad）。"""

    def test_missing_audio_returns_before_heavy_import(self):
        import whisperx_transcribe as WX
        r = WX.transcribe("/no/such/audio.wav")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error_code"], "audio_not_found")


class _FakeResp:
    """Minimal urlopen() stand-in: serves bytes in chunks via read(n)."""

    def __init__(self, data: bytes):
        self.headers = {"Content-Length": str(len(data))}
        self._buf = data

    def read(self, n):
        chunk, self._buf = self._buf[:n], self._buf[n:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class AsrModelDownloadTests(unittest.TestCase):
    """背景下載：串流寫 .part → 驗 sha1 → 原子搬到位；progress 可輪詢。不抓真檔。"""

    def _sandbox(self):
        tmp = Path(tempfile.mkdtemp(prefix="vi-asr-dl-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "tools/whisper.cpp/models").mkdir(parents=True)
        return tmp

    def test_download_verifies_and_installs(self):
        tmp = self._sandbox()
        payload = b"x" * (3 << 20)  # 3MB across multiple 1MB reads
        reg = {"tst": {"filename": "ggml-tst.bin", "url": "http://x", "sha1": hashlib.sha1(payload).hexdigest()}}
        with mock.patch.object(M, "_asr_root", return_value=tmp), \
             mock.patch.dict(M._ASR_MODEL_REGISTRY, reg), \
             mock.patch("urllib.request.urlopen", return_value=_FakeResp(payload)):
            M._ASR_MODEL_DOWNLOADS["tst"] = {"status": "downloading", "downloaded": 0, "total": 0, "error": ""}
            M._download_asr_model("tst")
            st = M._ASR_MODEL_DOWNLOADS["tst"]
            self.assertEqual(st["status"], "done")
            self.assertEqual(st["downloaded"], len(payload))
            self.assertTrue((tmp / "tools/whisper.cpp/models/ggml-tst.bin").is_file())
        M._ASR_MODEL_DOWNLOADS.pop("tst", None)

    def test_sha1_mismatch_discards_and_errors(self):
        tmp = self._sandbox()
        reg = {"tst": {"filename": "ggml-tst.bin", "url": "http://x", "sha1": "0" * 40}}
        with mock.patch.object(M, "_asr_root", return_value=tmp), \
             mock.patch.dict(M._ASR_MODEL_REGISTRY, reg), \
             mock.patch("urllib.request.urlopen", return_value=_FakeResp(b"corrupt")):
            M._ASR_MODEL_DOWNLOADS["tst"] = {"status": "downloading", "downloaded": 0, "total": 0, "error": ""}
            M._download_asr_model("tst")
            st = M._ASR_MODEL_DOWNLOADS["tst"]
            self.assertEqual(st["status"], "error")
            self.assertFalse((tmp / "tools/whisper.cpp/models/ggml-tst.bin").is_file())
            self.assertFalse((tmp / "tools/whisper.cpp/models/ggml-tst.bin.part").is_file())
        M._ASR_MODEL_DOWNLOADS.pop("tst", None)


class GlueParseTests(unittest.TestCase):
    """匯入既有逐字稿（make_vs_take GLUE）：SRT/VTT 帶時碼 → segments；純 TXT 無時碼 → []。"""

    def test_srt_parsed_to_timed_segments(self):
        from transcript import parse_imported_transcript
        srt = "1\n00:00:01,000 --> 00:00:04,000\n第一句\n\n2\n00:00:05,500 --> 00:00:07,000\n第二句\n"
        segs = parse_imported_transcript(srt, "m.srt")
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["start"], 1.0)
        self.assertEqual(segs[1]["start"], 5.5)
        self.assertEqual(segs[0]["text"], "第一句")

    def test_vtt_parsed(self):
        from transcript import parse_imported_transcript
        vtt = "WEBVTT\n\n00:00:02.000 --> 00:00:03.000\nhello\n"
        segs = parse_imported_transcript(vtt, "m.vtt")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["start"], 2.0)

    def test_generic_json_segments(self):
        from transcript import parse_imported_transcript
        js = '{"segments": [{"start": 12.0, "end": 14.0, "text": "x"}]}'
        segs = parse_imported_transcript(js, "whisper.json")
        self.assertEqual(segs, [{"text": "x", "start": 12.0, "duration": 2.0}])

    def test_plain_txt_has_no_timestamps(self):
        from transcript import parse_imported_transcript
        self.assertEqual(parse_imported_transcript("沒有時碼的純文字\n第二行", "notes.txt"), [])


class ImportTranscriptContractTests(unittest.TestCase):
    """import-transcript 路由：無 ASR、同步；摘要 mock 掉（no-spend）。
    機械保證——SRT 時碼 → [mm:ss] 餵進摘要 → distill 項無損渲染進 note；空輸入擋下。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vi-glue-"))

    def test_empty_text_blocked(self):
        result = R.app_state_import_transcript(R.ImportTranscriptReq(
            text="  ", vault_path=self.tmp.as_posix(), dry_run=True,
        ))
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "transcript_empty")

    def test_dry_run_reports_timestamps(self):
        srt = "1\n00:00:01,000 --> 00:00:03,000\n決議內容\n"
        result = R.app_state_import_transcript(R.ImportTranscriptReq(
            text=srt, filename="m.srt", vault_path=self.tmp.as_posix(), dry_run=True,
        ))
        self.assertTrue(result["ok"] and result["dry_run"])
        self.assertEqual(result["segment_count"], 1)
        self.assertTrue(result["has_timestamps"])
        self.assertEqual(result["provider_call_count"], 0)

    def test_write_passes_mmss_into_summary_and_note(self):
        srt = "1\n00:00:31,000 --> 00:00:34,000\n採 WhisperX\n"
        seen = {}

        def fake_summarize(transcript, template_id="general", glossary=None):
            seen["transcript"] = transcript
            seen["template_id"] = template_id
            seen["glossary"] = glossary
            return {"title": "匯入測試", "summary": "s", "decisions": ["採 WhisperX [00:31]"],
                    "action_items": [], "attendees": [], "agenda": [],
                    "key_organization": "", "core_value": ""}

        with mock.patch.object(R, "_summarize_meeting", side_effect=fake_summarize):
            result = R.app_state_import_transcript(R.ImportTranscriptReq(
                text=srt, filename="m.srt", vault_path=self.tmp.as_posix(), dry_run=False,
            ))
        self.assertTrue(result["ok"])
        self.assertIn("[00:31]", seen["transcript"])  # 時碼有餵進摘要層
        note = (self.tmp / result["write"]["relative_path"])
        self.assertTrue(note.is_file())
        self.assertIn("採 WhisperX [00:31]", note.read_text(encoding="utf-8"))  # distill 項無損渲染


class AsrTierAndLanguageDefaults(unittest.TestCase):
    """品質升級 Stage 1 機械半：強制語言 zh + tier→model resolver（stub，無音檔）。"""

    def test_meeting_req_defaults_language_zh(self):
        # 前端不傳 language → 後端預設生效；zh 消除 auto 偵測誤判
        self.assertEqual(R.MeetingNoteReq(audio_path="x").language, "zh")

    def test_meeting_req_tier_empty_by_default(self):
        self.assertEqual(R.MeetingNoteReq(audio_path="x").tier, "")

    def test_tier_maps_to_mode_and_model(self):
        self.assertEqual(M._resolve_asr_tier("快", "x", "y"), ("local", "small"))
        self.assertEqual(M._resolve_asr_tier("中", "x", "y"), ("local", "medium"))
        mode, model = M._resolve_asr_tier("高品質", "local", "base")
        self.assertEqual(mode, "cloud")
        self.assertEqual(model, "base")  # cloud tier 無內建 model → 沿用傳入

    def test_empty_or_unknown_tier_passes_through_explicit(self):
        self.assertEqual(M._resolve_asr_tier("", "whisperx", "medium"), ("whisperx", "medium"))
        self.assertEqual(M._resolve_asr_tier("unknown", "local", "base"), ("local", "base"))

    def test_tier_overrides_explicit_asr_model(self):
        # tier=中 覆蓋 frontend 明傳的 asr_model=base → 用 medium
        req = R.MeetingNoteReq(audio_path="x", asr_mode="local", asr_model="base", tier="中")
        self.assertEqual(M._resolve_asr_tier(req.tier, req.asr_mode, req.asr_model), ("local", "medium"))

    def test_precise_flips_local_tier_to_whisperx(self):
        # 精準/長音檔開關＝whisperx，只翻本地 tier；cloud 不受影響
        self.assertEqual(M._resolve_asr_tier("中", "x", "y", precise=True), ("whisperx", "medium"))
        self.assertEqual(M._resolve_asr_tier("快", "x", "y", precise=True), ("whisperx", "small"))
        self.assertEqual(M._resolve_asr_tier("高品質", "local", "base", precise=True), ("cloud", "base"))
        self.assertEqual(R.MeetingNoteReq(audio_path="x").precise, False)

    def test_fn_for_routes_tier_to_engine_simulated(self):
        """模擬（mock 引擎、無真音檔）：前端送 tier/precise → 對的引擎+模型+語言 zh。"""
        with mock.patch.object(M, "_meeting_asr_local", return_value="y") as loc:
            M._meeting_asr_fn_for(R.MeetingNoteReq(audio_path="a", tier="中"))(Path("a"))
            self.assertEqual(loc.call_args.args[1:], ("zh", "medium"))  # (path, language, model)
        with mock.patch.object(M, "_meeting_asr_whisperx", return_value="x") as wx:
            M._meeting_asr_fn_for(R.MeetingNoteReq(audio_path="a", tier="中", precise=True))(Path("a"))
            self.assertEqual(wx.call_args.args[1:], ("zh", "medium"))  # precise→whisperx
        with mock.patch.object(M, "_meeting_asr_local", return_value="y") as loc:
            M._meeting_asr_fn_for(R.MeetingNoteReq(audio_path="a", tier="快"))(Path("a"))
            self.assertEqual(loc.call_args.args[1:], ("zh", "small"))


class MeetingJobCancelTests(unittest.TestCase):
    """長任務取消（P1）：合作式 cancel 旗標 + 端點，無需音檔。"""

    def test_raise_if_cancelled(self):
        M._raise_if_cancelled({"cancel": False})  # no-op
        M._raise_if_cancelled({})                 # 缺鍵亦 no-op
        with self.assertRaises(M._JobCancelled):
            M._raise_if_cancelled({"cancel": True})

    def test_cancel_endpoint_sets_flag_and_404s_unknown(self):
        M._MEETING_JOBS["t-cancel"] = {"status": "running", "stage": "asr", "cancel": False}
        try:
            r = R.app_meeting_note_job_cancel("t-cancel")
            self.assertTrue(r["ok"])
            self.assertTrue(M._MEETING_JOBS["t-cancel"]["cancel"])
        finally:
            M._MEETING_JOBS.pop("t-cancel", None)
        with self.assertRaises(HTTPException):
            R.app_meeting_note_job_cancel("no-such-job")


class MeetingJobPersistenceTests(unittest.TestCase):
    """長任務狀態持久化（P1）：crash/重啟後仍查得到 job 結果，running→interrupted。"""

    def _clean(self, job_id):
        M._meeting_checkpoint_path(f"state_{job_id}").unlink(missing_ok=True)

    def test_persist_and_load_roundtrip(self):
        self.addCleanup(self._clean, "t-persist")
        M._persist_job_state("t-persist", {"status": "done", "stage": "written", "error": "",
                                           "audio_path": "/a.m4a", "write": {"relative_path": "x.md"}})
        d = M._load_job_state("t-persist")
        self.assertEqual(d["status"], "done")
        self.assertEqual(d["write"]["relative_path"], "x.md")

    def test_persisted_running_loads_as_interrupted(self):
        self.addCleanup(self._clean, "t-run")
        M._persist_job_state("t-run", {"status": "running", "stage": "asr", "error": "",
                                       "audio_path": "/a", "write": None})
        self.assertEqual(M._load_job_state("t-run")["status"], "interrupted")  # thread 已逝，不謊報 running

    def test_status_endpoint_falls_back_to_disk(self):
        self.addCleanup(self._clean, "t-disk")
        M._persist_job_state("t-disk", {"status": "done", "stage": "written", "error": "",
                                        "audio_path": "/a", "write": {"relative_path": "y.md"}})
        M._MEETING_JOBS.pop("t-disk", None)  # 記憶體沒（模擬重啟）
        r = R.app_meeting_note_job_status("t-disk")
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["write"]["relative_path"], "y.md")


if __name__ == "__main__":
    unittest.main()


class ValidateSummaryTimestampTests(unittest.TestCase):
    """機械強制可驗證：摘要 [mm:ss] 只保留對得回真實逐字稿 segment 的；杜撰/超出音檔 strip。"""

    def test_no_timestamp_transcript_strips_all(self):
        from meeting_note import validate_summary_timestamps
        out = validate_summary_timestamps({
            "decisions": ["預設語言鎖定中文 [00:00]", "改用 medium [00:00]"],
            "agenda": ["本週進度 [00:00]"], "core_value": "提升準度 [00:00]", "attendees": [],
        }, "整段沒有時間戳的逐字稿")
        self.assertEqual(out["decisions"], ["預設語言鎖定中文", "改用 medium"])
        self.assertEqual(out["agenda"], ["本週進度"])
        self.assertEqual(out["core_value"], "提升準度")

    def test_hallucinated_timestamps_stripped_real_kept(self):
        # JY 實測：36 秒音檔（真 segment 到 00:31），GPT 標 [00:40]/[00:45]＝幻覺超出 → strip；
        # 對得回真 segment 的 [00:23] → 保留。
        from meeting_note import validate_summary_timestamps
        transcript = "[00:00] a\n[00:06] b\n[00:11] c\n[00:23] d\n[00:31] e"
        out = validate_summary_timestamps({
            "action_items": ["接好下載流程 [00:40]", "補自動化測試 [00:45]"],
            "decisions": ["預設語言鎖定中文 [00:23]", "預設模型改 medium [00:35]"],
        }, transcript)
        self.assertEqual(out["action_items"], ["接好下載流程", "補自動化測試"])  # 幻覺全 strip
        self.assertEqual(out["decisions"], ["預設語言鎖定中文 [00:23]", "預設模型改 medium"])  # 真留假刪

    def test_fullwidth_timestamp_is_normalized_and_kept(self):
        from meeting_note import validate_summary_timestamps
        out = validate_summary_timestamps(
            {"decisions": ["預設語言鎖定中文【00:11】"]},
            "[00:00] a\n[00:11] 決議",
        )
        self.assertEqual(out["decisions"], ["預設語言鎖定中文 [00:11]"])
