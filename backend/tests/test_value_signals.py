"""Value-signal quality-layer tests (block #6).

Locks the typed signal projection and the quality verdict: complete
human-grade summaries pass clean, while auto-filled content_value, over-long
key_points, and missing fields raise review warnings.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import value_signals as VS  # noqa: E402


def _complete_summary():
    return {
        "explicit_topic": "Agentic AI 與 token 經濟",
        "key_points": "重點一\n重點二\n重點三",
        "terms": "NVIDIA\nJensen Huang",
        "content_value": "可對應到 AI 產品專案，建議加入雙向連結。",
        "source_platform": "YT",
        "content_category": "AI LLM",
    }


class BuildValueSignalsTests(unittest.TestCase):
    def test_complete_summary_is_clean(self):
        sig = VS.build_value_signals(_complete_summary())
        self.assertEqual(sig["key_point_count"], 3)
        self.assertEqual(sig["term_count"], 2)
        self.assertEqual(sig["key_points"], ["重點一", "重點二", "重點三"])
        self.assertEqual(sig["quality"]["completeness"], 1.0)
        self.assertEqual(sig["quality"]["warnings"], [])
        self.assertFalse(sig["quality"]["review_recommended"])
        self.assertFalse(sig["content_value_is_auto_placeholder"])

    def test_auto_placeholder_content_value_flagged(self):
        s = _complete_summary()
        s["content_value"] = VS.AUTO_CONTENT_VALUE_PREFIX + " 的內容提煉流程；參考依據：xxx"
        sig = VS.build_value_signals(s)
        self.assertTrue(sig["content_value_is_auto_placeholder"])
        self.assertIn("content_value_not_human_validated", sig["quality"]["warnings"])
        self.assertTrue(sig["quality"]["review_recommended"])

    def test_too_many_key_points_flagged(self):
        s = _complete_summary()
        s["key_points"] = "a\nb\nc\nd"
        sig = VS.build_value_signals(s)
        self.assertEqual(sig["key_point_count"], 4)
        self.assertIn("too_many_key_points", sig["quality"]["warnings"])

    def test_empty_summary_has_low_completeness_and_warnings(self):
        sig = VS.build_value_signals({})
        self.assertEqual(sig["quality"]["completeness"], 0.0)
        for expected in ("missing_topic", "missing_key_points", "missing_category"):
            self.assertIn(expected, sig["quality"]["warnings"])
        self.assertTrue(sig["quality"]["review_recommended"])


class ValueSignalsEndpointTests(unittest.TestCase):
    def test_endpoint_is_read_only_and_projects_signals(self):
        import routers.library as library
        resp = library.app_state_value_signals(library.ValueSignalsReq(summary=_complete_summary()))
        self.assertTrue(resp["read_only"])
        self.assertEqual(resp["value_signals"]["category"], "AI LLM")
        self.assertEqual(resp["value_signals"]["quality"]["warnings"], [])


if __name__ == "__main__":
    unittest.main()
