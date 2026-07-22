"""內建本機 LLM runtime（spec C）契約測試——無網路，全 mock 下載/子程序。"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import local_llm_builtin as B  # noqa: E402
import providers  # noqa: E402
from services import settings as S  # noqa: E402


class AssetSelectionTests(unittest.TestCase):
    def _asset(self, system, machine):
        with mock.patch.object(B.platform, "system", return_value=system), \
             mock.patch.object(B.platform, "machine", return_value=machine):
            return B.runtime_asset_name()

    def test_supported_platforms(self):
        self.assertIn("macos-arm64", self._asset("Darwin", "arm64"))
        self.assertIn("win-cpu-x64", self._asset("Windows", "AMD64"))
        self.assertIn("ubuntu-x64", self._asset("Linux", "x86_64"))

    def test_unsupported_platform_returns_none(self):
        self.assertIsNone(self._asset("Linux", "riscv64"))


class StatusAndInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(B.os.environ, {"YT_NOTE_ASR_ROOT": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
        B._DOWNLOADS.pop("install", None)

    def test_clean_machine_status(self):
        out = B.status()
        self.assertFalse(out["runtime_installed"])
        self.assertFalse(out["model_installed"])
        self.assertFalse(out["ready"])
        self.assertNotIn("download", out)

    def test_install_dedupes_while_downloading(self):
        B._DOWNLOADS["install"] = {"status": "downloading", "stage": "model",
                                   "downloaded": 5, "total": 10, "error": ""}
        with mock.patch.object(B.threading, "Thread") as thread:
            out = B.start_install()
        thread.assert_not_called()
        self.assertEqual(out["status"], "downloading")
        self.assertEqual(out["stage"], "model")

    def test_install_rejected_on_unsupported_platform(self):
        with mock.patch.object(B, "runtime_asset_name", return_value=None):
            with self.assertRaises(ValueError):
                B.start_install()

    def test_ready_when_binary_and_model_exist(self):
        root = Path(self.tmp.name) / "llama_runtime"
        binary = root / "runtime" / "build" / "bin" / "llama-server"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"#!x")
        model = root / "models" / B.MODEL_FILENAME
        model.parent.mkdir(parents=True)
        model.write_bytes(b"gguf")
        out = B.status()
        self.assertTrue(out["ready"])


class ChatTests(unittest.TestCase):
    def _respond(self, payload):
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps(payload).encode("utf-8")
        resp.__enter__ = mock.Mock(return_value=resp)
        resp.__exit__ = mock.Mock(return_value=False)
        return resp

    def test_chat_builds_openai_body_and_parses(self):
        payload = {"choices": [{"message": {"content": "嗨"}}],
                   "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
        with mock.patch.object(B, "ensure_server"), \
             mock.patch.object(B.urllib.request, "urlopen", return_value=self._respond(payload)) as opened:
            text, tokens = B.chat("hi", "sys", False, {"type": "object"}, 256)
        self.assertEqual(text, "嗨")
        self.assertEqual(tokens, {"input": 3, "output": 2})
        body = json.loads(opened.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(body["response_format"]["type"], "json_schema")

    def test_provider_routing_keyless_and_error_mapping(self):
        self.assertEqual(providers.detect_provider("llamacpp:gemma-3-4b-it"), "llamacpp")
        with mock.patch.object(providers.app_config, "get_provider_key") as get_key, \
             mock.patch("local_llm_builtin.chat", return_value=("好", {"input": 1, "output": 1})):
            out = providers.chat_complete(model=B.MODEL_ID, prompt="hi")
        get_key.assert_not_called()
        self.assertEqual(out["text"], "好")
        with mock.patch("local_llm_builtin.chat", side_effect=ValueError("尚未安裝")):
            with self.assertRaises(providers.ProviderError):
                providers.chat_complete(model=B.MODEL_ID, prompt="hi")

    def test_price_is_zero(self):
        import app_config
        self.assertEqual(app_config.price_for_model(B.MODEL_ID), (0.0, 0.0))


class OptionsMergeTests(unittest.TestCase):
    def test_cli_inventory_is_fixed_and_selectable_model_reaches_both_lanes(self):
        inventory = [
            {"id": "cli:claude", "label": "Claude（訂閱）", "state": "available"},
            {"id": "cli:codex", "label": "Codex（訂閱）", "state": "not_installed"},
            {"id": "cli:gemini", "label": "Gemini（訂閱）", "state": "call_failed"},
        ]
        option = {"id": "cli:claude", "label": "Claude（訂閱）", "provider": "cli"}
        with mock.patch.object(providers, "cli_inventory", return_value=inventory), \
             mock.patch.object(providers, "cli_options", return_value=[option]), \
             mock.patch.object(B, "status", return_value={"ready": False}):
            out = S.model_options()
        self.assertEqual(out["cli_inventory"], inventory)
        self.assertIn(option, out["translate"])
        self.assertIn(option, out["summary"])
        self.assertIn("cli", out["providers"])

    def test_builtin_appears_when_ready(self):
        with mock.patch.object(providers, "cli_options", return_value=[]), \
             mock.patch.object(B, "status", return_value={"ready": True}):
            out = S.model_options()
        self.assertIn("llamacpp", out["providers"])
        ids = [o["id"] for o in out["summary"]]
        self.assertIn(B.MODEL_ID, ids)

    def test_builtin_absent_when_not_ready(self):
        with mock.patch.object(providers, "cli_options", return_value=[]), \
             mock.patch.object(B, "status", return_value={"ready": False}):
            out = S.model_options()
        self.assertNotIn("llamacpp", out["providers"])


if __name__ == "__main__":
    unittest.main()
