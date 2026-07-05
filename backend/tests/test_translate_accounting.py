"""Translate usage-accounting + progress-feedback tests (findings #1, #2).

Finding #1: translate discarded provider usage (cost black hole vs summary).
Finding #2: long transcripts translate in many silent chunks (looks hung).
These mock the OpenAI client (no network/cost) to assert translate now logs an
aggregated usage event with provider_call_count = chunk count, and invokes the
progress callback once per chunk with an increasing index. The usage log is
redirected to a temp file so the real runtime log is not polluted.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MAX_CHARS = 6000  # mirrors translator.MAX_CHARS_PER_REQ


class _FakeUsage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c
        self.total_tokens = p + c


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self):
        self.choices = [_FakeChoice("翻譯")]
        self.usage = _FakeUsage(100, 50)


class _FakeCompletions:
    def __init__(self, recorder):
        self._recorder = recorder

    def create(self, **kwargs):
        self._recorder.append(kwargs)
        return _FakeResponse()


class _FakeOpenAI:
    calls: list = []

    def __init__(self, *args, **kwargs):
        self.chat = type("C", (), {"completions": _FakeCompletions(_FakeOpenAI.calls)})()


class TranslateAccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmplog = Path(tempfile.mkdtemp(prefix="vi-usage-")) / "usage.jsonl"
        os.environ["VAULTWIKI_RUNTIME_USAGE_LOG"] = str(self.tmplog)
        os.environ["OPENAI_API_KEY"] = "test-key-not-real"
        import openai
        _FakeOpenAI.calls = []
        openai.OpenAI = _FakeOpenAI
        # > MAX_CHARS to force multiple chunks
        self.text = ("word " * 2400).strip()

    def tearDown(self):
        os.environ.pop("VAULTWIKI_RUNTIME_USAGE_LOG", None)

    def test_progress_callback_fires_once_per_chunk(self):
        import translator
        seen = []
        translator.translate_to_zh(self.text, "zh-TW", progress_callback=lambda done, total: seen.append((done, total)))
        self.assertGreater(len(seen), 1, "long text should chunk into multiple calls")
        totals = {t for _, t in seen}
        self.assertEqual(len(totals), 1, "total stays constant")
        dones = [d for d, _ in seen]
        self.assertEqual(dones, list(range(1, len(seen) + 1)), "done increments per chunk")
        self.assertEqual(seen[-1][0], seen[-1][1], "final progress reaches total")

    def test_usage_event_logged_with_aggregated_tokens(self):
        import json
        import translator
        n_chunks = len(translator._chunk(self.text))
        translator.translate_to_zh(self.text, "zh-TW")
        events = [json.loads(l) for l in self.tmplog.read_text().splitlines() if l.strip()]
        translate_events = [e for e in events if e["task"] == "translate"]
        self.assertEqual(len(translate_events), 1)
        ev = translate_events[0]
        self.assertEqual(ev["provider_call_count"], n_chunks)
        self.assertEqual(ev["usage"]["confidence"], "exact")
        self.assertEqual(ev["usage"]["input_tokens"], 100 * n_chunks)
        self.assertEqual(ev["usage"]["output_tokens"], 50 * n_chunks)


if __name__ == "__main__":
    unittest.main()
