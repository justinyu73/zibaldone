"""_ocr_text_from_evidence：字幕框只放可讀文字，raw JSON 殘片不外漏。"""
from __future__ import annotations

import unittest

import production_extractor as PE


def _evidence(text: str) -> list[dict]:
    return [{"text": text}]


class OcrTextFromEvidenceTests(unittest.TestCase):
    def test_valid_json_in_fence_collects_entries(self):
        raw = '''前言雜訊
```json
{
  "hard_subtitles": [{"text": "第一句硬字幕", "language": "zh"}],
  "screen_text": [{"text": "畫面標題", "position": "top"}]
}
```'''
        result = PE._ocr_text_from_evidence(_evidence(raw))
        self.assertEqual(result, "第一句硬字幕\n畫面標題")

    def test_broken_json_fragment_leaks_no_raw_json(self):
        # 實際觀察到的殘片：entry 缺開頭大括號，json.loads 必失敗
        raw = '''```json
{
"hard_subtitles": [
"text": "已經配置好的subagent",
"language": "zh",
"style": "bold yellow text with black outline",
"position": "bottom center"
}
],
"screen_text": [
"text": "subagent",
"confidence": "medium"
'''
        result = PE._ocr_text_from_evidence(_evidence(raw))
        self.assertEqual(result, "已經配置好的subagent\nsubagent")

    def test_plain_text_fallback_unchanged(self):
        result = PE._ocr_text_from_evidence(_evidence("普通的一行\n第二行"))
        self.assertEqual(result, "普通的一行\n第二行")

    def test_dedupes_across_frames(self):
        evidence = [
            {"text": '{"hard_subtitles": [{"text": "重複句"}]}'},
            {"text": '{"hard_subtitles": [{"text": "重複句"}, {"text": "新句"}]}'},
        ]
        self.assertEqual(PE._ocr_text_from_evidence(evidence), "重複句\n新句")


if __name__ == "__main__":
    unittest.main()
