"""Keyless local OCR normalization tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from local_ocr import texts_from_result  # noqa: E402


class LocalOcrResultTests(unittest.TestCase):
    def test_normalizes_rapidocr_rows_and_ignores_empty_text(self):
        result = [
            [[[0, 0], [1, 0], [1, 1], [0, 1]], "第一行", 0.99],
            {"text": "第二行"},
            [[[0, 0]], "", 0.1],
        ]
        self.assertEqual(texts_from_result(result), ["第一行", "第二行"])


if __name__ == "__main__":
    unittest.main()
