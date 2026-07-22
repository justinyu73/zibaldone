"""Translate fallback chain (local-first): primary provider 失敗 → 走 config 的備援
model（例：雲端主→本地 llama.cpp），全鏈失敗才 raise。預設無 fallbacks＝行為不變。
無 provider/網路/spend：stub providers.chat_complete + model_policy。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class ModelsForTaskChainTests(unittest.TestCase):
    def test_chain_is_primary_plus_dedup_fallbacks(self):
        import model_policy
        orig = model_policy.load_model_policy
        model_policy.load_model_policy = lambda: {
            "tasks": {"translate": {"model": "gpt-x", "fallbacks": ["llamacpp:gemma-3-4b-it", "gpt-x", ""]}}
        }
        try:
            chain = model_policy.models_for_task("translate", "fb")
        finally:
            model_policy.load_model_policy = orig
        # primary first; repeated primary + empty dropped
        self.assertEqual(chain, ["gpt-x", "llamacpp:gemma-3-4b-it"])

    def test_no_fallbacks_is_single_model(self):
        import model_policy
        orig = model_policy.load_model_policy
        model_policy.load_model_policy = lambda: {"tasks": {"translate": {"model": "gpt-x"}}}
        try:
            self.assertEqual(model_policy.models_for_task("translate", "fb"), ["gpt-x"])
        finally:
            model_policy.load_model_policy = orig

    def test_selected_cli_route_never_adds_paid_fallback(self):
        import model_policy
        orig = model_policy.load_model_policy
        model_policy.load_model_policy = lambda: {
            "tasks": {"translate": {"model": "cli:codex", "fallbacks": ["gpt-5-mini"]}}
        }
        try:
            self.assertEqual(model_policy.models_for_task("translate", "fb"), ["cli:codex"])
        finally:
            model_policy.load_model_policy = orig


class TranslateFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmplog = Path(tempfile.mkdtemp(prefix="vi-fb-")) / "usage.jsonl"
        os.environ["VAULTWIKI_RUNTIME_USAGE_LOG"] = str(self.tmplog)
        import translator
        self._orig_models = translator.models_for_task

    def tearDown(self):
        os.environ.pop("VAULTWIKI_RUNTIME_USAGE_LOG", None)
        import translator
        translator.models_for_task = self._orig_models

    def test_fallback_to_local_when_primary_fails(self):
        import json
        import providers
        import translator
        translator.models_for_task = lambda task, fb="": ["gpt-primary", "llamacpp:gemma-3-4b-it"]
        orig_cc = providers.chat_complete

        def fake_cc(*, model, prompt, system=None, **kw):
            if model == "gpt-primary":
                raise providers.ProviderError("primary down")
            return {"text": "本地譯", "usage": {"confidence": "not_available"},
                    "provider": "llamacpp", "model": model}

        providers.chat_complete = fake_cc
        try:
            out = translator.translate_to_zh("hello world")
        finally:
            providers.chat_complete = orig_cc
        self.assertEqual(out, "本地譯")
        # usage event records the provider actually used (local fallback)
        events = [json.loads(l) for l in self.tmplog.read_text().splitlines() if l.strip()]
        self.assertEqual([e for e in events if e["task"] == "translate"][0]["provider"], "llamacpp")

    def test_whole_chain_failure_raises_translateerror(self):
        import providers
        import translator
        translator.models_for_task = lambda task, fb="": ["a", "b"]
        orig_cc = providers.chat_complete

        def boom(**kw):
            raise providers.ProviderError("down")

        providers.chat_complete = boom
        try:
            with self.assertRaises(translator.TranslateError):
                translator.translate_to_zh("hello")
        finally:
            providers.chat_complete = orig_cc


if __name__ == "__main__":
    unittest.main()
