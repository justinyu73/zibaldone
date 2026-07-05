"""Ollama 本地摘要 adapter（make_vs_take TAKE）：免金鑰、本地 HTTP、乾淨降級。
mock urllib，無 network / credential / cost。"""
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import providers  # noqa: E402
from services import settings as S  # noqa: E402


class _FakeHTTP:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._data


class OllamaDetectTests(unittest.TestCase):
    def test_detect_ollama_prefix(self):
        self.assertEqual(providers.detect_provider("ollama:qwen2.5"), "ollama")
        self.assertEqual(providers.detect_provider("gpt-5.2"), "openai")
        self.assertEqual(providers.detect_provider("claude-opus-4-8"), "anthropic")


class OllamaChatTests(unittest.TestCase):
    def test_chat_no_key_hits_local_chat(self):
        payload = {"message": {"content": '{"title":"x"}'}, "prompt_eval_count": 12, "eval_count": 8}
        with mock.patch.object(providers.urllib.request, "urlopen", return_value=_FakeHTTP(payload)) as uo:
            out = providers.chat_complete(model="ollama:qwen2.5", prompt="hi", json_mode=True)
        self.assertEqual(out["provider"], "ollama")
        self.assertEqual(out["text"], '{"title":"x"}')
        self.assertEqual(out["usage"]["total_tokens"], 20)
        req = uo.call_args[0][0]
        self.assertIn("/api/chat", req.full_url)
        body = json.loads(req.data.decode())
        self.assertEqual(body["model"], "qwen2.5")  # 前綴去掉
        self.assertEqual(body["format"], "json")  # json_mode → format=json

    def test_chat_unreachable_raises_friendly(self):
        with mock.patch.object(providers.urllib.request, "urlopen", side_effect=urllib.error.URLError("refused")):
            with self.assertRaises(providers.ProviderError):
                providers.chat_complete(model="ollama:qwen2.5", prompt="hi")


class OllamaTagsTests(unittest.TestCase):
    def test_tags_running(self):
        payload = {"models": [{"name": "qwen2.5:latest"}, {"name": "llama3"}]}
        with mock.patch.object(providers.urllib.request, "urlopen", return_value=_FakeHTTP(payload)):
            out = providers.ollama_tags()
        self.assertTrue(out["running"])
        self.assertEqual(out["models"], ["qwen2.5:latest", "llama3"])

    def test_tags_down_degrades(self):
        with mock.patch.object(providers.urllib.request, "urlopen", side_effect=urllib.error.URLError("x")):
            out = providers.ollama_tags()
        self.assertEqual(out, {"running": False, "models": []})


class ModelOptionsOllamaTests(unittest.TestCase):
    def test_merge_when_running(self):
        with mock.patch.object(providers, "ollama_tags", return_value={"running": True, "models": ["qwen2.5"]}):
            opts = S.model_options()
        self.assertIn("ollama:qwen2.5", [o["id"] for o in opts["summary"]])
        self.assertIn("ollama:qwen2.5", [o["id"] for o in opts["translate"]])
        self.assertIn("ollama", opts["providers"])

    def test_no_merge_when_down(self):
        with mock.patch.object(providers, "ollama_tags", return_value={"running": False, "models": []}):
            opts = S.model_options()
        self.assertFalse(any(str(o["id"]).startswith("ollama:") for o in opts["summary"]))


if __name__ == "__main__":
    unittest.main()
