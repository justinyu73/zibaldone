"""相關筆記：候選由標題/專有名詞命中聚合、排除自己與已鏈接、寫入 wikilink 段＋備份。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["YT_NOTE_APP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="vi-rel-cfg-")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from related_notes import SECTION, related_candidates, write_links  # noqa: E402


def _note(title, terms="", body=""):
    return (
        f"---\ntitle: {title}\n---\n\n"
        "<!-- vaultwiki:ai:start -->\n"
        "### 專有名詞 / 人物 / 工具\n"
        f"{terms}\n"
        "<!-- vaultwiki:ai:end -->\n\n"
        "## 個人心得筆記\n\n- \n\n"
        f"## 逐字稿\n\n{body}\n"
    )


class RelatedNotesTests(unittest.TestCase):
    def setUp(self):
        os.environ["YT_NOTE_APP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="vi-rel-cfg-")
        self.root = Path(tempfile.mkdtemp(prefix="vi-rel-vault-"))
        self.src = self.root / "02_Sources" / "youtube"
        self.src.mkdir(parents=True)
        (self.src / "main-note.md").write_text(_note("Prompt 工程實戰", "- Anthropic\n- Prompt caching"), encoding="utf-8")
        (self.src / "other-note.md").write_text(_note("Claude 開發筆記", body="講 Prompt caching 的細節"), encoding="utf-8")
        (self.src / "unrelated.md").write_text(_note("做菜筆記", body="紅燒肉"), encoding="utf-8")

    def test_candidates_hit_by_terms_excluding_self(self):
        result = related_candidates(str(self.root), "02_Sources/youtube/main-note.md")
        paths = [c["path"] for c in result["candidates"]]
        self.assertIn("02_Sources/youtube/other-note.md", paths)
        self.assertNotIn("02_Sources/youtube/main-note.md", paths)
        self.assertNotIn("02_Sources/youtube/unrelated.md", paths)
        self.assertIn("Prompt caching", result["candidates"][0]["matched"])

    def test_write_links_appends_wikilinks_with_backup_and_dedup(self):
        rel = "02_Sources/youtube/main-note.md"
        first = write_links(str(self.root), rel, ["02_Sources/youtube/other-note.md"])
        self.assertEqual(first["added"], 1)
        self.assertTrue(first.get("backup_path"))
        text = (self.root / rel).read_text(encoding="utf-8")
        self.assertIn(SECTION, text)
        self.assertIn("- [[other-note]]", text)
        self.assertLess(text.index(SECTION), text.index("## 逐字稿"))
        # 已鏈接的不重複寫；候選端也不再出現
        again = write_links(str(self.root), rel, ["02_Sources/youtube/other-note.md"])
        self.assertEqual(again["added"], 0)
        candidates = related_candidates(str(self.root), rel)["candidates"]
        self.assertNotIn("02_Sources/youtube/other-note.md", [c["path"] for c in candidates])


if __name__ == "__main__":
    unittest.main()
