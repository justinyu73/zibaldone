"""資訊雷達：掃描上限/指紋去重/重要標記/單源失敗隔離/RSS 解析。"""
import os
import tempfile
import unittest

os.environ["YT_NOTE_APP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="vi-radar-cfg-")

import radar
from radar import PER_SOURCE_CAP, dismiss, list_candidates, parse_feed, scan

RSS2 = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Announcing Model X</title><link>https://blog.example/x</link></item>
<item><title>Weekly notes</title><link>https://blog.example/notes</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Releasing toolkit</title><link href="https://site.example/toolkit"/></entry>
</feed>"""


def _stub(items):
    return lambda: items


class RadarTests(unittest.TestCase):
    def setUp(self):
        os.environ["YT_NOTE_APP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="vi-radar-cfg-")

    def test_scan_adds_marks_important_and_dedupes_on_rescan(self):
        fetchers = [("src", _stub([
            {"title": "Announcing Claude Fable 5", "url": "https://a.example/fable", "heat": "500 pts"},
            {"title": "一般文章", "url": "https://a.example/normal", "heat": ""},
        ]))]
        first = scan(fetchers=fetchers)
        self.assertEqual(first["added"], 2)
        listing = list_candidates()
        self.assertEqual(listing["total"], 2)
        self.assertTrue(listing["candidates"][0]["important"])  # 重要排最前
        second = scan(fetchers=fetchers)
        self.assertEqual(second["added"], 0)

    def test_dismiss_is_permanent_fingerprint(self):
        fetchers = [("src", _stub([{"title": "t", "url": "https://a.example/once"}]))]
        scan(fetchers=fetchers)
        target = list_candidates()["candidates"][0]["id"]
        dismiss([target])
        self.assertEqual(list_candidates()["total"], 0)
        again = scan(fetchers=fetchers)
        self.assertEqual(again["added"], 0)

    def test_per_source_cap(self):
        many = [{"title": f"t{i}", "url": f"https://a.example/{i}"} for i in range(PER_SOURCE_CAP + 15)]
        result = scan(fetchers=[("src", _stub(many))])
        self.assertEqual(result["added"], PER_SOURCE_CAP)

    def test_one_dead_source_does_not_kill_the_scan(self):
        def boom():
            raise RuntimeError("network down")
        result = scan(fetchers=[("dead", boom), ("ok", _stub([{"title": "t", "url": "https://b.example/1"}]))])
        self.assertEqual(result["added"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("dead", result["errors"][0])

    def test_tuning_caps_apply_and_coerce_strings(self):
        many = [{"title": f"t{i}", "url": f"https://c.example/{i}"} for i in range(30)]
        result = scan(fetchers=[("src", _stub(many))], tuning={"per_source_cap": "5", "total_cap": 5})
        self.assertEqual(result["added"], 5)

    def test_tuning_bad_values_fall_back_to_defaults(self):
        t = radar._normalize_tuning({"total_cap": "abc", "per_source_cap": None, "keywords": [" Rust ", ""], "enable_hn": 0})
        self.assertEqual(t["total_cap"], radar.DEFAULT_TUNING["total_cap"])
        self.assertEqual(t["per_source_cap"], radar.DEFAULT_TUNING["per_source_cap"])
        self.assertEqual(t["keywords"], ["rust"])
        self.assertFalse(t["enable_hn"])

    def test_all_sources_disabled_scans_nothing(self):
        result = scan(tuning={"enable_hn": False, "enable_github": False, "enable_rss": False})
        self.assertEqual(result["added"], 0)
        self.assertEqual(result["errors"], [])

    def test_custom_keywords_replace_builtin_ai_filter(self):
        self.assertTrue(radar._ai_related("Shipping a new Rust toolchain", ["rust"]))
        self.assertFalse(radar._ai_related("Announcing GPT-5", ["rust"]))
        self.assertTrue(radar._ai_related("Announcing GPT-5"))  # 留空＝內建 AI 詞庫

    def test_parse_feed_handles_rss2_and_atom(self):
        rss_items = parse_feed(RSS2, "https://blog.example/rss.xml")
        self.assertEqual([i["url"] for i in rss_items], ["https://blog.example/x", "https://blog.example/notes"])
        atom_items = parse_feed(ATOM, "https://site.example/feed")
        self.assertEqual(atom_items[0]["url"], "https://site.example/toolkit")
        self.assertEqual(atom_items[0]["source"], "site.example")

    def test_fresh_filter_skips_old_rss_dates(self):
        old_rss = (b"<?xml version=\"1.0\"?><rss version=\"2.0\"><channel>"
                   b"<item><title>old</title><link>https://b.example/old</link>"
                   b"<pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item>"
                   b"</channel></rss>")
        self.assertEqual(parse_feed(old_rss, "https://b.example/rss"), [])


if __name__ == "__main__":
    unittest.main()
