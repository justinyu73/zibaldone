"""退場候選：Type1 過時參考入候選；Type2 永不入；被 Type2 引用的舊 Type1 豁免（防呆）。"""
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

os.environ["YT_NOTE_APP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="vi-ret-cfg-")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retirement import classify, is_excluded, retirement_candidates  # noqa: E402

TODAY = date(2026, 6, 23)


def _type1(title, created, source_type="article", url="https://example.com/x", body=""):
    return (
        f"---\ntitle: {title}\nsource_type: {source_type}\nsource_url: {url}\n"
        f"created: {created}\n---\n\n{body}\n"
    )


def _type2(title, created, body=""):
    return f"---\ntitle: {title}\ncreated: {created}\n---\n\n{body}\n"


class ClassifyTests(unittest.TestCase):
    def test_under_sources_is_type1(self):
        self.assertEqual(classify("02_Sources/articles/manual/x.md", "title: x"), "type1")

    def test_digest_under_sources_is_type1(self):
        # JY 裁示：時事聚合 digest 當 Type1 走 90d（即使無 source_url）
        self.assertEqual(classify("02_Sources/daily/ai-digest.md", "title: digest"), "type1")

    def test_source_url_outside_sources_is_type1(self):
        self.assertEqual(classify("misc/x.md", 'title: x\nsource_url: "https://a/b"'), "type1")

    def test_root_handwritten_is_type2(self):
        self.assertEqual(classify("委任合約測試法.md", "title: 委任合約"), "type2")

    def test_knowledge_folder_handwritten_is_type2(self):
        self.assertEqual(classify("03_System/arch-decision.md", "title: 架構"), "type2")


class ExclusionTests(unittest.TestCase):
    def test_readme_excluded(self):
        self.assertTrue(is_excluded("02_Sources/daily/README.md"))
        self.assertTrue(is_excluded("01_Inbox/_README.md"))

    def test_trash_excluded(self):
        self.assertTrue(is_excluded("02_Sources/facebook/_trash/x.md"))

    def test_inbox_excluded(self):
        self.assertTrue(is_excluded("01_Inbox/manual-intake/x.md"))

    def test_normal_not_excluded(self):
        self.assertFalse(is_excluded("02_Sources/articles/manual/x.md"))


class RetirementCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="vi-ret-vault-"))
        (self.root / "02_Sources").mkdir(parents=True)
        (self.root / "03_System").mkdir(parents=True)

    def _write(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_stale_type1_becomes_candidate(self):
        self._write("02_Sources/old-harness-tut.md", _type1("Harness 教學", "2026-01-01"))
        result = retirement_candidates(str(self.root), stale_days=90, today=TODAY)
        stems = [c["stem"] for c in result["candidates"]]
        self.assertIn("old-harness-tut", stems)

    def test_fresh_type1_not_candidate(self):
        self._write("02_Sources/new-tut.md", _type1("新教學", "2026-06-01"))
        result = retirement_candidates(str(self.root), stale_days=90, today=TODAY)
        self.assertEqual(result["candidates"], [])

    def test_type2_never_candidate_even_if_old(self):
        self._write("03_System/arch-decision.md", _type2("改版原因節點", "2020-01-01"))
        result = retirement_candidates(str(self.root), stale_days=90, today=TODAY)
        self.assertEqual(result["candidates"], [])

    def test_old_type1_referenced_by_type2_is_exempt(self):
        # 防呆：架構筆記(Type2)還在引用的舊教學(Type1)不入候選
        self._write("02_Sources/cited-tut.md", _type1("被引用的舊教學", "2025-01-01"))
        self._write(
            "03_System/arch.md",
            _type2("系統架構", "2026-06-01", body="## 相關筆記\n\n- [[cited-tut]]\n"),
        )
        result = retirement_candidates(str(self.root), stale_days=90, today=TODAY)
        stems = [c["stem"] for c in result["candidates"]]
        self.assertNotIn("cited-tut", stems)

    def test_missing_created_not_candidate(self):
        self._write("02_Sources/no-date.md", _type1("無日期", "", url="https://a/b"))
        result = retirement_candidates(str(self.root), stale_days=90, today=TODAY)
        self.assertEqual(result["candidates"], [])

    def test_counts_and_sort(self):
        self._write("02_Sources/a.md", _type1("A", "2026-01-01"))   # 173d
        self._write("02_Sources/b.md", _type1("B", "2025-06-23"))   # 365d
        self._write("03_System/s.md", _type2("S", "2024-01-01"))
        result = retirement_candidates(str(self.root), stale_days=90, today=TODAY)
        self.assertEqual(result["scanned"], 3)
        self.assertEqual([c["stem"] for c in result["candidates"]], ["b", "a"])


if __name__ == "__main__":
    unittest.main()
