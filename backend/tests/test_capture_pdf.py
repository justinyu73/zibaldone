"""markitdown v1: 01_Inbox PDF → md 筆記（原檔移 _attachments、壞檔明確錯誤）."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["YT_NOTE_APP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="vi-pdf-cfg-")

import capture_inbox  # noqa: E402
from capture_inbox import OcrUnavailable, convert_pdf_capture, scan_capture_inbox  # noqa: E402

# 最小但合法、含可抽取文字的 PDF（單頁 "Hello PDF"）
MINI_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 44>>stream
BT /F1 24 Tf 72 720 Td (Hello PDF) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
trailer<</Size 6/Root 1 0 R>>
startxref
0
%%EOF
"""


class CapturePdfTest(unittest.TestCase):
    def setUp(self):
        os.environ["YT_NOTE_APP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="vi-pdf-cfg-")
        self.vault = Path(tempfile.mkdtemp(prefix="vi-pdf-vault-"))
        (self.vault / "01_Inbox").mkdir(parents=True)

    def test_scan_lists_pdf_candidate(self):
        (self.vault / "01_Inbox" / "paper.pdf").write_bytes(MINI_PDF)
        out = scan_capture_inbox(str(self.vault))
        pdfs = [c for c in out["items"] if c["kind"] == "pdf"]
        self.assertEqual(len(pdfs), 1)
        self.assertEqual(pdfs[0]["file"], "paper.pdf")

    def test_convert_writes_note_and_moves_original(self):
        (self.vault / "01_Inbox" / "paper.pdf").write_bytes(MINI_PDF)
        result = convert_pdf_capture(str(self.vault), "paper.pdf")
        self.assertTrue(result["ok"], result)
        # 原檔移入 _attachments
        self.assertFalse((self.vault / "01_Inbox" / "paper.pdf").exists())
        self.assertTrue((self.vault / "_attachments" / "paper.pdf").exists())
        # 筆記存在、status inbox、含轉出文字與附件連結
        notes = list((self.vault / "02_Sources" / "articles").glob("*.md"))
        self.assertEqual(len(notes), 1)
        text = notes[0].read_text(encoding="utf-8")
        self.assertIn("status: inbox", text)
        self.assertIn("Hello PDF", text)
        self.assertIn("_attachments/paper.pdf", text)
        # 指紋已記：重掃不再出現
        out = scan_capture_inbox(str(self.vault))
        self.assertEqual([c for c in out["items"] if c["kind"] == "pdf"], [])

    def test_corrupt_pdf_gives_clear_error(self):
        (self.vault / "01_Inbox" / "bad.pdf").write_bytes(b"not a pdf at all")
        result = convert_pdf_capture(str(self.vault), "bad.pdf")
        self.assertFalse(result["ok"])
        self.assertIn(result["reason"], ("invalid_pdf", "convert_failed", "empty_text"))
        self.assertTrue(result["message"])  # 有人話錯誤訊息
        # 原檔不動
        self.assertTrue((self.vault / "01_Inbox" / "bad.pdf").exists())

    def test_scanned_pdf_falls_back_to_ocr(self):
        # markitdown 出空＝無文字層（掃描型）→ OCR 補救；不依賴真 OCR 套件
        (self.vault / "01_Inbox" / "scan.pdf").write_bytes(MINI_PDF)
        with mock.patch.object(capture_inbox, "_markitdown_text", return_value=""), \
             mock.patch.object(capture_inbox, "_ocr_pdf", return_value="OCR 抽出的文字"):
            result = convert_pdf_capture(str(self.vault), "scan.pdf")
        self.assertTrue(result["ok"], result)
        note = next((self.vault / "02_Sources" / "articles").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("OCR 抽出的文字", note)
        self.assertIn("## 原文（PDF OCR）", note)

    def test_scanned_pdf_without_ocr_component_gives_clear_error(self):
        (self.vault / "01_Inbox" / "scan.pdf").write_bytes(MINI_PDF)
        with mock.patch.object(capture_inbox, "_markitdown_text", return_value=""), \
             mock.patch.object(capture_inbox, "_ocr_pdf", side_effect=OcrUnavailable("no rapidocr")):
            result = convert_pdf_capture(str(self.vault), "scan.pdf")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "ocr_unavailable")
        self.assertIn("OCR", result["message"])
        self.assertTrue((self.vault / "01_Inbox" / "scan.pdf").exists())  # 原檔不動

    def test_scanned_pdf_ocr_empty_gives_empty_text(self):
        (self.vault / "01_Inbox" / "scan.pdf").write_bytes(MINI_PDF)
        # _ocr_pdf 真實回傳已 strip；讀不出＝空字串
        with mock.patch.object(capture_inbox, "_markitdown_text", return_value=""), \
             mock.patch.object(capture_inbox, "_ocr_pdf", return_value=""):
            result = convert_pdf_capture(str(self.vault), "scan.pdf")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "empty_text")

    def test_path_escape_rejected(self):
        result = convert_pdf_capture(str(self.vault), "../outside.pdf")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
