"""免費翻譯：分段、合併、錯誤面。"""
import json
import unittest

from free_translate import MAX_CHARS_PER_REQ, FreeTranslateError, _chunks, free_translate_to_zh


def _fake_fetch(query: str) -> bytes:
    # echo back a gtx-shaped response: one segment per request
    return json.dumps([[["譯文段", "orig", None]]]).encode()


class FreeTranslateTests(unittest.TestCase):
    def test_short_text_single_request(self):
        self.assertEqual(free_translate_to_zh("hello world", fetch_fn=_fake_fetch), "譯文段")

    def test_long_text_chunked_and_joined(self):
        text = "\n".join(["paragraph " * 50] * 30)  # 超過單請求上限
        chunks = _chunks(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= MAX_CHARS_PER_REQ for c in chunks))
        out = free_translate_to_zh(text, fetch_fn=_fake_fetch)
        self.assertEqual(out, "\n".join(["譯文段"] * len(chunks)))

    def test_endpoint_failure_raises_actionable_error(self):
        def boom(query):
            raise OSError("blocked")
        with self.assertRaises(FreeTranslateError):
            free_translate_to_zh("hello", fetch_fn=boom)


if __name__ == "__main__":
    unittest.main()
