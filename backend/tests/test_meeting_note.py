"""Meeting voice-note v1 tests (new direction).

Locks the orchestration + summary normalization with stubs (no audio bytes sent
to a provider, no spend): file-exists + size guard, dry-run skips ASR/spend/
write, live sequences ASR → summarize → write, and the 8 meeting fields are
structured with a quality verdict.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import meeting_note as M  # noqa: E402


class _Spy:
    def __init__(self, ret):
        self.calls = 0
        self.ret = ret

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.ret


def _full_summary():
    return {
        "title": "Q2 規劃會議",
        "summary": "討論 Q2 產品優先序與資源分配。",
        "key_organization": "決定先做 A 再做 B",
        "core_value": "對齊跨團隊優先序，降低重工",
        "action_items": ["JY 出規格", "工程估時"],
        "decisions": "採方案 A",
        "attendees": ["JY", "PM", "Eng"],
        "agenda": "1. 優先序\n2. 資源",
    }


class NormalizeMeetingSummaryTests(unittest.TestCase):
    def test_full_summary_parses_lists_and_is_complete(self):
        s = M.normalize_meeting_summary(_full_summary())
        self.assertEqual(s["action_items"], ["JY 出規格", "工程估時"])
        self.assertEqual(s["decisions"], ["採方案 A"])  # string -> single-item list
        self.assertEqual(s["attendees"], ["JY", "PM", "Eng"])
        self.assertEqual(s["agenda"], ["1. 優先序", "2. 資源"])
        self.assertEqual(s["quality"]["completeness"], 1.0)
        self.assertEqual(s["quality"]["warnings"], [])

    def test_rich_llm_shapes_flatten_not_repr(self):
        # The LLM often returns dict items / lists where the schema expects flat
        # strings; the note must read as text, never a Python repr.
        s = M.normalize_meeting_summary({
            "key_organization": ["脈絡一", "脈絡二"],          # list for a string field
            "action_items": [{"item": "出規格", "owner": "JY", "due_date": "週四"}],
            "agenda": [{"topic": "優先序", "notes": ["子題A", "子題B"]}],
        })
        self.assertEqual(s["key_organization"], "- 脈絡一\n- 脈絡二")
        self.assertEqual(s["action_items"], ["出規格 — JY — 週四"])
        self.assertEqual(s["agenda"], ["優先序 — 子題A；子題B"])
        md = M.build_meeting_markdown(s, "逐字稿", "/tmp/m.m4a", today="2026-06-07")
        self.assertNotIn("{'", md)  # no dict repr leaked into the note
        self.assertNotIn("['", md)  # no list repr leaked into the note

    def test_missing_core_fields_warn(self):
        s = M.normalize_meeting_summary({"summary": "x"})
        self.assertIn("missing_title", s["quality"]["warnings"])
        self.assertIn("missing_core_value", s["quality"]["warnings"])
        self.assertTrue(s["quality"]["review_recommended"])


class RunMeetingNoteTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="vi-meet-"))
        self.audio = self.dir / "meeting.m4a"
        self.audio.write_bytes(b"x" * 2048)

    def _stubs(self):
        return _Spy("逐字稿..."), _Spy(_full_summary()), _Spy({"relative_path": "meetings/q2.md"})

    def test_missing_audio_stops_at_intake(self):
        result = M.run_meeting_note(str(self.dir / "nope.m4a"), asr_fn=_Spy(""), summarizer_fn=_Spy({}), writer_fn=_Spy({}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "audio_file_not_found")

    def test_oversize_audio_blocked(self):
        result = M.run_meeting_note(str(self.audio), asr_fn=_Spy(""), summarizer_fn=_Spy({}), writer_fn=_Spy({}), max_audio_bytes=10)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "audio_too_large")

    def test_dry_run_previews_without_asr_or_write(self):
        asr, sm, wr = self._stubs()
        result = M.run_meeting_note(str(self.audio), asr_fn=asr, summarizer_fn=sm, writer_fn=wr, dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["would_write_to"], M.MEETINGS_SUBFOLDER)
        self.assertEqual((asr.calls, sm.calls, wr.calls), (0, 0, 0))

    def test_live_sequences_asr_summarize_write(self):
        asr, sm, wr = self._stubs()
        result = M.run_meeting_note(str(self.audio), asr_fn=asr, summarizer_fn=sm, writer_fn=wr, dry_run=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["stage"], "written")
        self.assertEqual(result["summary"]["title"], "Q2 規劃會議")
        self.assertEqual((asr.calls, sm.calls, wr.calls), (1, 1, 1))


class MeetingMarkdownTests(unittest.TestCase):
    def test_markdown_has_all_sections(self):
        md = M.build_meeting_markdown(M.normalize_meeting_summary(_full_summary()), "逐字稿內容", "/tmp/meeting.m4a", today="2026-06-07")
        for section in ("# Q2 規劃會議", "## 摘要", "## 重要整理", "## 核心價值", "## 議程", "## 行動項目", "## 決議", "## 出席者", "## 逐字稿"):
            self.assertIn(section, md)
        self.assertIn("audio_source: meeting.m4a", md)
        self.assertIn("- JY 出規格", md)

    def test_write_meeting_note_writes_to_meetings_dir(self):
        vault = Path(tempfile.mkdtemp(prefix="vi-mvault-"))
        summary = M.normalize_meeting_summary(_full_summary())
        result = M.write_meeting_note(str(vault), summary, "逐字稿", "/tmp/m.m4a")
        self.assertTrue(result["relative_path"].startswith(M.MEETINGS_SUBFOLDER))
        self.assertTrue((vault / result["relative_path"]).exists())

    def test_meetings_subfolder_derives_from_vault_root_without_nesting(self):
        # Regression (audit B4): vault_path is the vault ROOT; the old
        # "note_study/..." prefix created youtube/note_study/... nesting.
        self.assertEqual(M.MEETINGS_SUBFOLDER, "02_Sources/meetings")
        vault = Path(tempfile.mkdtemp(prefix="vi-mvault-"))
        result = M.write_meeting_note(str(vault), M.normalize_meeting_summary(_full_summary()), "逐字稿", "/tmp/m.m4a")
        self.assertNotIn("note_study", result["relative_path"])


class AsrHallucinationFilterTests(unittest.TestCase):
    """批次轉錄套幻覺片語過濾：whisper 在靜音/語言不符時的罐頭幻覺整行丟。"""
    def test_strips_known_hallucination_phrases(self):
        import services.meetings
        text = "真正的會議重點\n請不吝點贊 訂閱 轉發 打賞支援明鏡與點點欄目\n下一段正常內容"
        got = services.meetings._strip_asr_hallucinations(text)
        self.assertNotIn("明鏡", got)
        self.assertNotIn("請不吝", got)
        self.assertIn("真正的會議重點", got)
        self.assertIn("下一段正常內容", got)


if __name__ == "__main__":
    unittest.main()


class CloudFabricatedTimestampIntegrationTests(unittest.TestCase):
    """重現 JY Op-Demo 失敗：雲端 ASR 回無逐句時間戳的逐字稿 + GPT 摘要杜撰 [00:00]
    （連 prompt 沒要時間戳的 agenda 都被塞）→ run_meeting_note 應機械 strip 乾淨。"""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="vi-meet-fab-"))
        self.audio = self.dir / "meeting.m4a"
        self.audio.write_bytes(b"x" * 2048)

    def _fabricating_summary(self, _transcript):
        # 雲端 gpt-4o 實測行為：每條（含 agenda）硬塞 [00:00]，無視「不杜撰」prompt
        return {
            "title": "轉錄品質會議", "summary": "討論轉錄品質升級。",
            "key_organization": "語言鎖中文 [00:00]", "core_value": "提升準度 [00:00]",
            "action_items": ["本週接好下載流程 [00:00]", "補自動化測試 [00:00]"],
            "decisions": ["預設語言鎖定中文 [00:00]", "預設模型改 medium [00:00]"],
            "attendees": [], "agenda": ["本週進度確認 [00:00]"],
        }

    def test_no_timestamp_transcript_strips_fabricated_mmss(self):
        # 雲端單段逐字稿（_timestamped_transcript guard 後＝純文字、無 [mm:ss]）
        asr = lambda _p: "今天開會討論轉錄品質升級，決議鎖定中文，預設模型改 medium。"
        result = M.run_meeting_note(str(self.audio), asr_fn=asr,
            summarizer_fn=self._fabricating_summary,
            writer_fn=lambda d: {"relative_path": "meetings/x.md"}, dry_run=False)
        self.assertTrue(result["ok"])
        s = result["summary"]
        for field in ("action_items", "decisions", "agenda"):
            self.assertTrue(all("[" not in item for item in s[field]),
                            f"{field} 仍含杜撰時間戳：{s[field]}")
        self.assertNotIn("[00:00]", s["core_value"])
        self.assertEqual(s["decisions"], ["預設語言鎖定中文", "預設模型改 medium"])

    def test_real_timestamp_transcript_keeps_attribution(self):
        # 對照：逐字稿真有 [mm:ss]（本地多段）→ 摘要真時間戳保留，不誤刪
        asr = lambda _p: "[00:06] 決議鎖定中文\n[00:23] 改用 medium"
        sm = lambda _t: {"title": "t", "summary": "s", "key_organization": "", "core_value": "",
            "action_items": [], "decisions": ["改用 medium [00:23]"], "attendees": [], "agenda": []}
        result = M.run_meeting_note(str(self.audio), asr_fn=asr, summarizer_fn=sm,
            writer_fn=lambda d: {"relative_path": "meetings/y.md"}, dry_run=False)
        self.assertEqual(result["summary"]["decisions"], ["改用 medium [00:23]"])
