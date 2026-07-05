"""本機 LLM（Ollama）status/pull 路由契約測試——stdlib unittest、無網路，全 mock ollama。"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import routers.meetings as M  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def _tags(running: bool, models: list[str]):
    return {"running": running, "models": models}


class LocalLlmStatusTests(unittest.TestCase):
    def tearDown(self):
        M._OLLAMA_PULLS.pop(M._OLLAMA_RECOMMENDED_MODEL, None)

    def test_not_running(self):
        with mock.patch.object(M.providers, "ollama_tags", return_value=_tags(False, [])):
            out = M.app_local_llm_status()
        self.assertFalse(out["running"])
        self.assertFalse(out["recommended_installed"])
        self.assertNotIn("pull", out)

    def test_running_with_recommended_installed(self):
        with mock.patch.object(M.providers, "ollama_tags",
                               return_value=_tags(True, ["gemma3:4b", "llama3:8b"])):
            out = M.app_local_llm_status()
        self.assertTrue(out["running"])
        self.assertTrue(out["recommended_installed"])
        self.assertEqual(out["recommended"], "gemma3:4b")

    def test_status_carries_pull_progress(self):
        M._OLLAMA_PULLS[M._OLLAMA_RECOMMENDED_MODEL] = {
            "status": "downloading", "downloaded": 5, "total": 10, "error": ""}
        with mock.patch.object(M.providers, "ollama_tags", return_value=_tags(True, [])):
            out = M.app_local_llm_status()
        self.assertEqual(out["pull"]["status"], "downloading")
        self.assertEqual(out["pull"]["downloaded"], 5)


class LocalLlmPullTests(unittest.TestCase):
    def tearDown(self):
        M._OLLAMA_PULLS.pop("gemma3:4b", None)

    def test_pull_rejected_when_ollama_not_running(self):
        with mock.patch.object(M.providers, "ollama_tags", return_value=_tags(False, [])):
            with self.assertRaises(HTTPException) as ctx:
                M.app_local_llm_pull(M.OllamaPullReq())
        self.assertEqual(ctx.exception.status_code, 400)

    def test_pull_short_circuits_when_installed(self):
        with mock.patch.object(M.providers, "ollama_tags", return_value=_tags(True, ["gemma3:4b"])):
            out = M.app_local_llm_pull(M.OllamaPullReq())
        self.assertTrue(out["already_installed"])
        self.assertNotIn("gemma3:4b", M._OLLAMA_PULLS)

    def test_pull_starts_thread_and_dedupes(self):
        with mock.patch.object(M.providers, "ollama_tags", return_value=_tags(True, [])), \
             mock.patch.object(M.threading, "Thread") as thread:
            first = M.app_local_llm_pull(M.OllamaPullReq())
            second = M.app_local_llm_pull(M.OllamaPullReq())
        self.assertEqual(first["status"], "downloading")
        self.assertEqual(second["status"], "downloading")
        thread.assert_called_once()  # 第二次命中進行中 → 不重複起執行緒
        self.assertEqual(M._OLLAMA_PULLS["gemma3:4b"]["status"], "downloading")


class PullWorkerTests(unittest.TestCase):
    def tearDown(self):
        M._OLLAMA_PULLS.pop("gemma3:4b", None)

    def _run_worker(self, lines: list[bytes], tags_after: dict):
        resp = mock.MagicMock()
        resp.__enter__ = mock.Mock(return_value=iter(lines))
        resp.__exit__ = mock.Mock(return_value=False)
        M._OLLAMA_PULLS["gemma3:4b"] = {"status": "downloading", "downloaded": 0, "total": 0, "error": ""}
        with mock.patch("urllib.request.urlopen", return_value=resp), \
             mock.patch.object(M.providers, "ollama_tags", return_value=tags_after):
            M._pull_ollama_model("gemma3:4b")
        return M._OLLAMA_PULLS["gemma3:4b"]

    def test_progress_lines_then_done(self):
        lines = [
            b'{"status":"pulling x","total":100,"completed":40}',
            b'{"status":"pulling x","total":100,"completed":100}',
            b'{"status":"success"}',
        ]
        state = self._run_worker(lines, _tags(True, ["gemma3:4b"]))
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["downloaded"], 100)
        self.assertEqual(state["total"], 100)

    def test_ollama_error_line_surfaces(self):
        state = self._run_worker([b'{"error":"no space left"}'], _tags(True, []))
        self.assertEqual(state["status"], "error")
        self.assertIn("no space left", state["error"])

    def test_missing_model_after_pull_is_error(self):
        state = self._run_worker([b'{"status":"success"}'], _tags(True, []))
        self.assertEqual(state["status"], "error")


if __name__ == "__main__":
    unittest.main()
