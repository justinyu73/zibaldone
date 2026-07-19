"""1a 判讀翻譯 fallback：gtx 被擋時走使用者設定的 LLM、記帳；無金鑰回明確錯誤。
直接呼叫端點函數並 mock 依賴（repo 慣例：stdlib unittest，不引 TestClient）。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["YT_NOTE_APP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="vi-ft-cfg-")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import free_translate  # noqa: E402
import routers.library as library  # noqa: E402
import providers  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class FreeTranslateFallbackTests(unittest.TestCase):
    def _req(self, text="hello world"):
        return library.FreeTranslateReq(text=text)

    def test_gtx_success_does_not_fall_back(self):
        with mock.patch.object(free_translate, "free_translate_to_zh", return_value="你好世界") as gtx, \
             mock.patch.object(providers, "chat_complete") as cc:
            out = library.app_state_free_translate(self._req())
        gtx.assert_called_once()
        cc.assert_not_called()  # gtx 成功就不該碰 LLM
        self.assertEqual(out["provider"], "google-gtx-free")
        self.assertEqual(out["translated"], "你好世界")

    def test_gtx_blocked_falls_back_to_llm_when_key_set(self):
        with mock.patch.object(free_translate, "free_translate_to_zh",
                               side_effect=free_translate.FreeTranslateError("blocked")), \
             mock.patch.object(library.app_config, "get_settings", return_value={"translate_model": "gpt-4o-mini"}), \
             mock.patch.object(library.app_config, "get_provider_key", return_value="sk-test"), \
             mock.patch.object(library, "_check_daily_cap"), \
             mock.patch.object(library, "append_runtime_usage_event") as usage, \
             mock.patch.object(providers, "detect_provider", return_value="openai"), \
             mock.patch.object(providers, "chat_complete",
                               return_value={"text": "翻譯結果", "usage": {"input_tokens": 5, "output_tokens": 3}}) as cc:
            out = library.app_state_free_translate(self._req())
        cc.assert_called_once()           # 真的走了 LLM
        usage.assert_called_once()        # 有記帳
        self.assertEqual(out["provider"], "llm-fallback:gpt-4o-mini")
        self.assertIn("翻譯結果", out["translated"])

    def test_gtx_blocked_without_key_raises_clear_error(self):
        with mock.patch.object(free_translate, "free_translate_to_zh",
                               side_effect=free_translate.FreeTranslateError("blocked")), \
             mock.patch.object(library.app_config, "get_settings", return_value={"translate_model": "gpt-4o-mini"}), \
             mock.patch.object(library.app_config, "get_provider_key", return_value=""), \
             mock.patch.object(providers, "detect_provider", return_value="openai"), \
             mock.patch.object(providers, "chat_complete") as cc:
            with self.assertRaises(HTTPException) as ctx:
                library.app_state_free_translate(self._req())
        cc.assert_not_called()            # 無金鑰不該呼叫付費 LLM
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("金鑰", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
