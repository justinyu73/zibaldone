"""Approved paid-stage executor tests (block #5-live).

Locks the safety contract: a paid stage refuses BEFORE calling the provider
when the estimate exceeds the per-job cap (no spend), and only delegates to the
injected provider callable when within cap. Pure stubs — no network, no spend.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import job_executor as JE  # noqa: E402
from loop_cost import CostCapExceeded  # noqa: E402


class _Spy:
    def __init__(self, ret):
        self.calls = 0
        self.ret = ret

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.ret


class JobExecutorTests(unittest.TestCase):
    def _executor(self, cap, translator, summarizer=None, writer=None):
        return JE.JobExecutor(
            translator_fn=translator,
            summarizer_fn=summarizer or _Spy({}),
            writer_fn=writer or _Spy({}),
            per_job_cap_usd=cap,
        )

    def test_translate_refuses_before_provider_call_when_over_cap(self):
        translator = _Spy("zh")
        ex = self._executor(0.0001, translator)  # tiny cap -> over
        with self.assertRaises(CostCapExceeded):
            ex.run_translate("word " * 5000)
        self.assertEqual(translator.calls, 0, "provider must NOT be called when over cap")

    def test_translate_runs_provider_when_within_cap(self):
        translator = _Spy("翻譯結果")
        ex = self._executor(0.03, translator)
        out = ex.run_translate("hello world")
        self.assertEqual(out, "翻譯結果")
        self.assertEqual(translator.calls, 1)

    def test_summarize_is_also_cap_gated(self):
        summarizer = _Spy({"explicit_topic": "t"})
        ex = self._executor(0.0001, _Spy("zh"), summarizer=summarizer)
        with self.assertRaises(CostCapExceeded):
            ex.run_summarize("word " * 5000, "Title", "url")
        self.assertEqual(summarizer.calls, 0)

    def test_write_delegates_to_writer(self):
        writer = _Spy({"relative_path": "smoke/x.md"})
        ex = self._executor(0.03, _Spy("zh"), writer=writer)
        res = ex.run_write(path="smoke/x.md", content="body")
        self.assertEqual(res["relative_path"], "smoke/x.md")
        self.assertEqual(writer.calls, 1)


if __name__ == "__main__":
    unittest.main()
