"""Canonical source-to-note orchestrator tests (convergence step 1).

Stubs all external effects to lock the orchestration contract: the cost cap is
enforced BEFORE any paid call, no-CC stops with an operator-upload next action,
dry-run spends nothing and writes nothing, and a live run drives translate →
summarize → value-signals → write in order.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import source_to_note as S  # noqa: E402


class _Spy:
    def __init__(self, ret):
        self.calls = 0
        self.ret = ret

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.ret


def _cc_source(en="word " * 100):
    return {"title": "Demo", "channel": "Ch", "en_text": en, "zh_text": "", "has_cc": True, "languages": ["en"]}


class SourceToNoteTests(unittest.TestCase):
    def _run(self, *, source, cap=0.03, dry_run=True, translator=None, summarizer=None, writer=None):
        translator = translator or _Spy("zh")
        summarizer = summarizer or _Spy({"explicit_topic": "t", "content_category": "AI"})
        writer = writer or _Spy({"relative_path": "youtube/videos/demo.md", "created_new": True})
        result = S.run_source_to_note(
            video_id="vid1", url="https://youtu.be/vid1", per_job_cap_usd=cap,
            fetch_fn=lambda v: source, translator_fn=translator, summarizer_fn=summarizer,
            writer_fn=writer, dry_run=dry_run,
        )
        return result, translator, summarizer, writer

    def test_invalid_video_id_stops_at_extract(self):
        result = S.run_source_to_note(
            video_id="", url="x", per_job_cap_usd=0.03,
            fetch_fn=lambda v: {}, translator_fn=_Spy("z"), summarizer_fn=_Spy({}), writer_fn=_Spy({}),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "extract")

    def test_no_captions_stops_and_routes_to_operator_upload(self):
        src = {"title": "NoCC", "has_cc": False, "en_text": "", "zh_text": ""}
        result, tr, sm, wr = self._run(source=src)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "no_captions")
        self.assertEqual(result["next_action"], "operator_upload_for_asr")
        self.assertEqual((tr.calls, sm.calls, wr.calls), (0, 0, 0))

    def test_over_cap_blocks_before_any_paid_call(self):
        src = _cc_source(en="word " * 50000)  # huge -> over cap
        result, tr, sm, wr = self._run(source=src, cap=0.001)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "cost_preflight")
        self.assertEqual((tr.calls, sm.calls, wr.calls), (0, 0, 0), "no paid call when over cap")

    def test_dry_run_previews_without_spend_or_write(self):
        result, tr, sm, wr = self._run(source=_cc_source(), dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertIn("estimate", result)
        self.assertEqual((tr.calls, sm.calls, wr.calls), (0, 0, 0), "dry-run spends/writes nothing")

    def test_live_runs_full_pipeline_in_order(self):
        result, tr, sm, wr = self._run(source=_cc_source(), dry_run=False)
        self.assertTrue(result["ok"])
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["stage"], "written")
        self.assertIn("value_signals", result)
        self.assertEqual(result["write"]["created_new"], True)
        self.assertEqual((tr.calls, sm.calls, wr.calls), (1, 1, 1))


class _FakeMeta:
    title = "Endpoint Demo"
    channel = "Ch"
    published = None
    duration = None
    thumbnail = None


if __name__ == "__main__":
    unittest.main()
