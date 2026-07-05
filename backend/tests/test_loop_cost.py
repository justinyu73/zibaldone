"""Cost preflight + cap-enforcement tests for the source-to-note loop.

Pins the cost model against the real #4 run (77,370 chars cost ~$0.016) and
locks that an over-cap job is refused BEFORE any paid call.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import loop_cost as LC  # noqa: E402


class LoopCostEstimateTests(unittest.TestCase):
    def test_matches_real_run_order_of_magnitude(self):
        est = LC.estimate_source_to_note_cost(77370)
        self.assertEqual(est.transcript_chars, 77370)
        # real #4 run landed ~$0.015-0.016
        self.assertGreater(est.total_usd, 0.012)
        self.assertLess(est.total_usd, 0.020)
        # translate dominates over summary
        self.assertGreater(est.translate_usd, est.summary_usd)

    def test_summary_input_is_capped(self):
        # Beyond the summary char cap, summary cost stops growing; only translate does.
        small = LC.estimate_source_to_note_cost(24000)
        big = LC.estimate_source_to_note_cost(240000)
        self.assertAlmostEqual(small.summary_usd, big.summary_usd, places=6)
        self.assertGreater(big.translate_usd, small.translate_usd)

    def test_as_dict_shape(self):
        d = LC.estimate_source_to_note_cost(1000).as_dict()
        self.assertEqual(
            set(d), {"translate_usd", "summary_usd", "total_usd", "transcript_chars"}
        )


class CostCapEnforcementTests(unittest.TestCase):
    def test_within_cap_passes(self):
        est = LC.estimate_source_to_note_cost(77370)
        LC.enforce_cost_cap(est, 0.03)  # must not raise

    def test_over_cap_raises(self):
        est = LC.estimate_source_to_note_cost(77370)
        with self.assertRaises(LC.CostCapExceeded):
            LC.enforce_cost_cap(est, 0.001)

    def test_huge_transcript_exceeds_default_cap(self):
        est = LC.estimate_source_to_note_cost(500000)
        with self.assertRaises(LC.CostCapExceeded):
            LC.enforce_cost_cap(est, 0.03)

    def test_nonpositive_cap_is_rejected(self):
        est = LC.estimate_source_to_note_cost(1000)
        with self.assertRaises(LC.CostCapExceeded):
            LC.enforce_cost_cap(est, 0)


if __name__ == "__main__":
    unittest.main()
