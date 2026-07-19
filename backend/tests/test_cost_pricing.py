"""Per-provider cost pricing (closes the routing gap where every model was
priced at the OpenAI rate). The cost display + daily cap must price each usage
event by its own model, fall back conservatively for unknown models, and honor
a config override. No network, no real key, no cost.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_config  # noqa: E402


class PriceForModelTests(unittest.TestCase):
    def test_known_models_keep_distinct_prices(self):
        self.assertEqual(app_config.price_for_model("gpt-5-mini"), (0.15, 0.60))
        self.assertEqual(app_config.price_for_model("claude-opus-4-8"), (15.0, 75.0))

    def test_unknown_model_falls_back_conservative_high(self):
        # An unpriced model must NOT default to the cheap OpenAI rate, or the cap under-counts.
        self.assertEqual(
            app_config.price_for_model("brand-new-unlisted-model"),
            app_config.CONSERVATIVE_DEFAULT_PRICE,
        )

    def test_config_override_wins(self):
        cfg = Path(tempfile.mkdtemp(prefix="vi-price-")) / "config.json"
        cfg.write_text(json.dumps({"model_prices": {"gpt-5-mini": {"input": 9.0, "output": 9.0}}}))
        orig = app_config.CONFIG_FILE
        app_config.CONFIG_FILE = cfg
        try:
            self.assertEqual(app_config.price_for_model("gpt-5-mini"), (9.0, 9.0))
        finally:
            app_config.CONFIG_FILE = orig


class RetiredModelMigrationTests(unittest.TestCase):
    def test_stored_retired_gemini_migrates_to_current(self):
        cfg = Path(tempfile.mkdtemp(prefix="vi-retire-")) / "config.json"
        cfg.write_text(json.dumps({"translate_model": "gemini-2.0-flash", "summary_model": "gemini-1.5-pro"}))
        orig = app_config.CONFIG_FILE
        app_config.CONFIG_FILE = cfg
        try:
            settings = app_config.get_settings()
            self.assertEqual(settings["translate_model"], "gemini-3.5-flash")
            self.assertEqual(settings["summary_model"], "gemini-3.1-pro")
        finally:
            app_config.CONFIG_FILE = orig

    def test_retired_models_absent_from_options_and_prices(self):
        from services import settings

        ids = [o["id"] for group in ("translate", "summary") for o in settings.MODEL_OPTIONS[group]]
        for retired in app_config.RETIRED_MODEL_MAP:
            self.assertNotIn(retired, ids)
            self.assertNotIn(retired, app_config.DEFAULT_MODEL_PRICES)


class CostSummaryPerModelTests(unittest.TestCase):
    def test_each_event_priced_by_its_own_model(self):
        log = Path(tempfile.mkdtemp(prefix="vi-cost-")) / "usage.jsonl"
        os.environ["VAULTWIKI_RUNTIME_USAGE_LOG"] = str(log)
        rows = [
            {"model": "gpt-5-mini", "usage": {"input_tokens": 1_000_000, "output_tokens": 0}, "provider_call_count": 1, "observed_at": "2000-01-01"},
            {"model": "claude-opus-4-8", "usage": {"input_tokens": 1_000_000, "output_tokens": 0}, "provider_call_count": 1, "observed_at": "2000-01-01"},
        ]
        log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        from services import settings

        summary = settings._cost_summary()
        # gpt-5-mini input @0.15 + opus-4-8 input @15.0 = 15.15 (not 0.30 at a flat OpenAI rate).
        self.assertEqual(summary["total_usd"], round(0.15 + 15.0, 4))
        self.assertEqual(summary["total_calls"], 2)


if __name__ == "__main__":
    unittest.main()
