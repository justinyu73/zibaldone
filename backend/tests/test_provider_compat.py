"""Provider-compatibility regression tests (block #4b bug fix).

Live 4b found that translate/summary passed temperature=0.2, which the
configured gpt-5.x models reject (400: only the default value is supported),
so every real provider call failed. These tests mock the OpenAI client to
capture the create() kwargs and lock in that neither call sends an unsupported
`temperature` param. No network, no real key, no cost.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _redirect_usage_log():
    """Keep usage-log side effects out of the real runtime log during tests."""
    os.environ["VAULTWIKI_RUNTIME_USAGE_LOG"] = str(
        Path(tempfile.mkdtemp(prefix="vi-compat-")) / "usage.jsonl"
    )


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]
        self.usage = None


class _FakeCompletions:
    def __init__(self, recorder, content):
        self._recorder = recorder
        self._content = content

    def create(self, **kwargs):
        self._recorder.append(kwargs)
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, recorder, content):
        self.completions = _FakeCompletions(recorder, content)


class _FakeOpenAI:
    calls: list = []
    content = "{}"

    def __init__(self, *args, **kwargs):
        self.chat = _FakeChat(_FakeOpenAI.calls, _FakeOpenAI.content)


def _patch_openai(content):
    import openai
    _FakeOpenAI.calls = []
    _FakeOpenAI.content = content
    openai.OpenAI = _FakeOpenAI
    return _FakeOpenAI.calls


class TranslateProviderCompatTests(unittest.TestCase):
    def test_translate_does_not_send_temperature(self):
        os.environ["OPENAI_API_KEY"] = "test-key-not-real"
        _redirect_usage_log()
        import translator
        os.environ["OPENAI_TRANSLATE_MODEL"] = "gpt-5-mini"  # pin：不受本機 ambient 設定（如 ollama）影響
        calls = _patch_openai("翻譯結果")
        out = translator.translate_to_zh("hello world", "zh-TW")
        self.assertEqual(out, "翻譯結果")
        self.assertTrue(calls, "expected at least one provider call")
        for kwargs in calls:
            self.assertNotIn("temperature", kwargs, "gpt-5.x rejects non-default temperature")
            self.assertIn("model", kwargs)
            self.assertIn("messages", kwargs)


class SummarizeProviderCompatTests(unittest.TestCase):
    def test_summarize_does_not_send_temperature(self):
        os.environ["OPENAI_API_KEY"] = "test-key-not-real"
        _redirect_usage_log()
        import main  # noqa: F401 — bootstrap side effects（dotenv/apply_settings_to_env）順序不變
        import routers.capture as capture
        os.environ["OPENAI_SUMMARY_MODEL"] = "gpt-5.2"  # pin（在 apply_settings_to_env 後，免被本機 ollama 設定蓋掉）
        calls = _patch_openai(
            '{"explicit_topic":"t","key_points":["a"],"terms":["x"],'
            '"content_value":"v","source_platform":"YT","content_category":"AI"}'
        )
        resp = capture.summarize(capture.SummarizeReq(title="Demo", transcript_en="hello world", mode="quick"))
        self.assertIn("summary", resp)
        self.assertTrue(calls, "expected a summary provider call")
        for kwargs in calls:
            self.assertNotIn("temperature", kwargs, "gpt-5.x rejects non-default temperature")
            self.assertEqual(kwargs.get("response_format"), {"type": "json_object"})


if __name__ == "__main__":
    unittest.main()
