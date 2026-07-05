"""Cost breakdown (模型火力與花費表單)：per-model 聚合 + 型態(本地/雲) + range 過濾。
無 provider/網路：直接寫 craft 的 usage jsonl，呼叫 services.settings._cost_breakdown。"""
import json
import os
import sys
import time
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class CostBreakdownTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vi-cost-")) / "usage.jsonl"
        today = time.strftime("%Y-%m-%d")
        rows = [
            # 雲端 model A：2 events 同 model 應聚合
            {"task": "summary", "provider": "openai", "model": "gpt-5.2", "provider_call_count": 1,
             "observed_at": f"{today}T01:00:00", "usage": {"input_tokens": 100, "output_tokens": 50}},
            {"task": "translate", "provider": "openai", "model": "gpt-5.2", "provider_call_count": 2,
             "observed_at": f"{today}T02:00:00", "usage": {"input_tokens": 200, "output_tokens": 80}},
            # 本地 ollama model B
            {"task": "translate", "provider": "ollama", "model": "ollama:qwen2.5:3b", "provider_call_count": 1,
             "observed_at": f"{today}T03:00:00", "usage": {"input_tokens": 1000, "output_tokens": 300}},
            # estimate-only (0 calls) 不計
            {"task": "summary", "provider": "openai", "model": "gpt-5.2", "provider_call_count": 0,
             "observed_at": f"{today}T04:00:00", "usage": {"input_tokens": 999, "output_tokens": 999}},
        ]
        self.tmp.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        os.environ["VAULTWIKI_RUNTIME_USAGE_LOG"] = str(self.tmp)

    def tearDown(self):
        os.environ.pop("VAULTWIKI_RUNTIME_USAGE_LOG", None)

    def test_brand_model_hierarchy_kind_and_aggregation(self):
        from services import settings
        bd = settings._cost_breakdown("month")
        brands = {g["brand"]: g for g in bd["brands"]}
        # 大分類 OpenAI（雲）含 gpt-5.2，兩筆聚合（estimate-only 不計）
        self.assertEqual(brands["OpenAI"]["kind"], "cloud")
        gpt = {m["model"]: m for m in brands["OpenAI"]["models"]}["gpt-5.2"]
        self.assertEqual(gpt["calls"], 3)            # 1+2
        self.assertEqual(gpt["input_tokens"], 300)   # 100+200
        self.assertEqual(gpt["output_tokens"], 130)  # 50+80
        self.assertEqual(gpt["total_tokens"], 430)
        # brand 層聚合 = 旗下 model 之和
        self.assertEqual(brands["OpenAI"]["total_tokens"], 430)
        # 大分類 本機（local）
        self.assertEqual(brands["本機"]["kind"], "local")
        self.assertEqual(brands["本機"]["total_tokens"], 1300)
        # 總 token（estimate-only 999+999 不計）
        self.assertEqual(bd["total_tokens"], 1730)
        self.assertIn("本月", bd["range_label"])

    def test_custom_range_filters_both_bounds(self):
        from services import settings
        rows = [
            {"task": "summary", "provider": "openai", "model": "m1", "provider_call_count": 1,
             "observed_at": "2026-06-10T00:00:00", "usage": {"input_tokens": 10, "output_tokens": 0}},
            {"task": "summary", "provider": "openai", "model": "m2", "provider_call_count": 1,
             "observed_at": "2026-06-15T00:00:00", "usage": {"input_tokens": 20, "output_tokens": 0}},
            {"task": "summary", "provider": "openai", "model": "m3", "provider_call_count": 1,
             "observed_at": "2026-06-20T00:00:00", "usage": {"input_tokens": 40, "output_tokens": 0}},
        ]
        self.tmp.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        bd = settings._cost_breakdown(start_date="2026-06-12", end_date="2026-06-18")
        models = {m["model"] for g in bd["brands"] for m in g["models"]}
        self.assertEqual(models, {"m2"})  # 06-10 在下界外、06-20 在上界外 → 排除
        self.assertEqual(bd["range"], "custom")
        self.assertIn("自訂", bd["range_label"])
        self.assertEqual(bd["total_tokens"], 20)

    def test_today_range_excludes_old(self):
        from services import settings
        old = {"task": "summary", "provider": "openai", "model": "gpt-old", "provider_call_count": 1,
               "observed_at": "2020-01-01T00:00:00", "usage": {"input_tokens": 5, "output_tokens": 5}}
        with self.tmp.open("a", encoding="utf-8") as f:
            f.write(json.dumps(old) + "\n")
        bd = settings._cost_breakdown("today")
        all_models = {m["model"] for g in bd["brands"] for m in g["models"]}
        self.assertNotIn("gpt-old", all_models)


if __name__ == "__main__":
    unittest.main()
