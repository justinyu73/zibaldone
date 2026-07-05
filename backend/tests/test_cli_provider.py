"""訂閱 CLI provider（spec B）契約測試——stdlib unittest、無網路，全 mock which/subprocess。"""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import providers  # noqa: E402


def _proc(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class DetectProviderTests(unittest.TestCase):
    def test_cli_prefix_routes_to_cli(self):
        self.assertEqual(providers.detect_provider("cli:claude"), "cli")
        self.assertEqual(providers.detect_provider("CLI:codex"), "cli")

    def test_existing_prefixes_unchanged(self):
        self.assertEqual(providers.detect_provider("ollama:gemma3:4b"), "ollama")
        self.assertEqual(providers.detect_provider("claude-sonnet-4-6"), "anthropic")
        self.assertEqual(providers.detect_provider("gpt-5-mini"), "openai")


class CliOptionsTests(unittest.TestCase):
    def setUp(self):
        # 預設關（S2 TOS 閘）——本組測「開啟後」的偵測行為
        self.enabled = mock.patch.object(
            providers.app_config, "get_settings",
            return_value={"cli_providers_enabled": True})
        self.enabled.start()

    def tearDown(self):
        self.enabled.stop()

    def test_only_installed_tools_appear(self):
        with mock.patch.object(providers, "_cli_path",
                               side_effect=lambda name: "/bin/x" if name == "claude" else None):
            options = providers.cli_options()
        self.assertEqual([o["id"] for o in options], ["cli:claude"])
        self.assertEqual(options[0]["provider"], "cli")
        self.assertIn("訂閱", options[0]["label"])

    def test_none_installed_yields_empty(self):
        with mock.patch.object(providers, "_cli_path", return_value=None):
            self.assertEqual(providers.cli_options(), [])

    def test_disabled_by_default_even_when_installed(self):
        self.enabled.stop()
        try:
            with mock.patch.object(providers, "_cli_path", return_value="/bin/x"), \
                 mock.patch.object(providers.app_config, "load_app_config", return_value={}):
                self.assertEqual(providers.cli_options(), [])
        finally:
            self.enabled.start()

    def test_path_fallback_scans_beyond_which(self):
        # which 撲空但常見安裝位置有 → 仍要找到（GUI app 極簡 PATH 情境）
        with mock.patch.object(providers.shutil, "which", return_value=None), \
             mock.patch.object(providers.os.path, "isfile", return_value=True), \
             mock.patch.object(providers.os, "access", return_value=True):
            path = providers._cli_path("claude")
        self.assertTrue(path and path.endswith("/claude"))


class CliChatTests(unittest.TestCase):
    def _run(self, run_result=None, run_side_effect=None, **kwargs):
        with mock.patch.object(providers, "_cli_path", return_value="/bin/claude"), \
             mock.patch.object(providers.subprocess, "run",
                               return_value=run_result, side_effect=run_side_effect) as run:
            out = providers.chat_complete(model="cli:claude", prompt="hi", **kwargs)
        return out, run

    def test_success_returns_text_and_zero_usage(self):
        out, run = self._run(run_result=_proc(stdout="答案\n"))
        self.assertEqual(out["text"], "答案")
        self.assertEqual(out["provider"], "cli")
        self.assertEqual(out["usage"]["total_tokens"], 0)
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "/bin/claude")  # 絕對路徑替換 argv[0]
        self.assertEqual(argv[1], "-p")
        self.assertIn("--output-format", argv)

    def test_no_key_required(self):
        with mock.patch.object(providers.app_config, "get_provider_key") as get_key:
            out, _ = self._run(run_result=_proc(stdout="ok"))
        get_key.assert_not_called()
        self.assertEqual(out["text"], "ok")

    def test_system_and_json_schema_folded_into_prompt(self):
        _, run = self._run(run_result=_proc(stdout="{}"), system="系統規則",
                           json_mode=True, json_schema={"type": "object"})
        sent = run.call_args.args[0][2]
        self.assertTrue(sent.startswith("系統規則"))
        self.assertIn("JSON Schema", sent)

    def test_nonzero_exit_surfaces_last_stderr_line(self):
        with self.assertRaises(providers.ProviderError) as ctx:
            self._run(run_result=_proc(stderr="boom\nnot logged in", returncode=1))
        self.assertIn("not logged in", str(ctx.exception))
        self.assertIn("claude", str(ctx.exception))

    def test_empty_stdout_is_failure(self):
        with self.assertRaises(providers.ProviderError):
            self._run(run_result=_proc(stdout="   "))

    def test_timeout_maps_to_provider_error(self):
        with self.assertRaises(providers.ProviderError) as ctx:
            self._run(run_side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=300))
        self.assertIn("逾時", str(ctx.exception))

    def test_not_installed_maps_to_provider_error(self):
        with mock.patch.object(providers, "_cli_path", return_value=None):
            with self.assertRaises(providers.ProviderError) as ctx:
                providers.chat_complete(model="cli:claude", prompt="hi")
        self.assertIn("未安裝", str(ctx.exception))

    def test_unknown_tool_rejected(self):
        with self.assertRaises(providers.ProviderError):
            providers.chat_complete(model="cli:rm-rf", prompt="hi")


class PriceTests(unittest.TestCase):
    def test_cli_models_cost_zero(self):
        import app_config
        self.assertEqual(app_config.price_for_model("cli:claude"), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
