"""Offline unit tests for the normalized area metric (Option A).

Pure stdlib `unittest`. No Vitis, no LLM, no network. Verifies the
utilization sum, capacity fallback, defensive None handling, the area-delay
product's throughput preference order, and the growth ratio. Run either way::

    python3 -m unittest tests.test_area -v
    python3 tests/test_area.py
"""

from __future__ import annotations

import os
import sys
import unittest

# Allow `python3 tests/test_area.py` (repo root not on sys.path otherwise).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harpo.area import (
    DEVICE_CAPS,
    adp,
    area_score,
    resource_growth_ratio,
)

# Realistic mac8_001 samples (see task prompt). part-only -> DEVICE_CAPS caps.
RECIPE_BEST = {
    "lut": 315, "ff": 126, "dsp": 0, "bram_18k": 0,
    "interval_max": 256, "part": "xc7z020-clg400-1",
}
LLM_BLOWUP = {
    "lut": 13194, "ff": 322,
    "interval_max": 128, "part": "xc7z020-clg400-1",
}


class TestAreaScore(unittest.TestCase):
    def test_explicit_avail(self):
        # Caps come straight from the metrics dict, not the fallback table.
        m = {
            "lut": 1000, "ff": 2000, "dsp": 10,
            "avail_lut": 10000, "avail_ff": 20000, "avail_dsp": 100,
        }
        # 0.1 + 0.1 + 0.1 = 0.3
        self.assertAlmostEqual(area_score(m), 0.3, places=6)

    def test_fallback_to_device_caps_by_part(self):
        caps = DEVICE_CAPS["xc7z020-clg400-1"]
        expected = 315 / caps["lut"] + 126 / caps["ff"]  # dsp/bram are 0 count
        self.assertAlmostEqual(area_score(RECIPE_BEST), expected, places=9)

    def test_part_lookup_tolerant_of_speed_grade(self):
        # Custom caps table keyed WITHOUT the trailing speed grade still resolves.
        caps = {"xc7z020-clg400": {"lut": 100, "ff": 100, "dsp": 1, "bram_18k": 1, "uram": 0}}
        m = {"lut": 50, "part": "xc7z020-clg400-1"}
        self.assertAlmostEqual(area_score(m, caps=caps), 0.5, places=9)

    def test_none_and_empty_metrics(self):
        self.assertIsNone(area_score(None))
        self.assertIsNone(area_score({}))

    def test_counts_but_no_known_caps(self):
        # Counts present, but no avail_*, no caps, and an unknown part.
        self.assertIsNone(area_score({"lut": 500, "ff": 500, "part": "unknown-part"}))
        # No part at all -> no fallback table entry either.
        self.assertIsNone(area_score({"lut": 500, "ff": 500}))

    def test_uram_zero_capacity_contributes_nothing(self):
        # uram has a count but DEVICE_CAPS gives it capacity 0 -> skipped, no raise.
        m = {"lut": 315, "uram": 4, "part": "xc7z020-clg400-1"}
        expected = 315 / DEVICE_CAPS["xc7z020-clg400-1"]["lut"]
        self.assertAlmostEqual(area_score(m), expected, places=9)

    def test_non_numeric_values_ignored(self):
        # None/strings must not raise; only the valid lut count survives.
        m = {"lut": 315, "ff": None, "dsp": "n/a", "part": "xc7z020-clg400-1"}
        expected = 315 / DEVICE_CAPS["xc7z020-clg400-1"]["lut"]
        self.assertAlmostEqual(area_score(m), expected, places=9)

    def test_recipe_smaller_than_llm_blowup(self):
        # The whole point: the recipe design uses far less area than the LLM one.
        self.assertLess(area_score(RECIPE_BEST), area_score(LLM_BLOWUP))


class TestADP(unittest.TestCase):
    def test_prefers_interval_max(self):
        m = {"lut": 1000, "avail_lut": 10000,
             "interval_max": 256, "latency_worst": 999, "ii": 7}
        # area 0.1 * interval_max 256
        self.assertAlmostEqual(adp(m), 0.1 * 256, places=6)

    def test_falls_back_to_latency_worst(self):
        m = {"lut": 1000, "avail_lut": 10000, "latency_worst": 500, "ii": 7}
        self.assertAlmostEqual(adp(m), 0.1 * 500, places=6)

    def test_falls_back_to_ii(self):
        m = {"lut": 1000, "avail_lut": 10000, "ii": 4}
        self.assertAlmostEqual(adp(m), 0.1 * 4, places=6)

    def test_none_when_throughput_missing(self):
        m = {"lut": 1000, "avail_lut": 10000}  # no throughput key at all
        self.assertIsNone(adp(m))

    def test_none_when_area_missing(self):
        # Throughput present but no usable area.
        self.assertIsNone(adp({"interval_max": 128}))
        self.assertIsNone(adp(None))


class TestResourceGrowthRatio(unittest.TestCase):
    def test_basic_ratio(self):
        ratio = resource_growth_ratio(LLM_BLOWUP, RECIPE_BEST)
        expected = area_score(LLM_BLOWUP) / area_score(RECIPE_BEST)
        self.assertAlmostEqual(ratio, expected, places=9)
        self.assertGreater(ratio, 1.0)  # LLM design grew vs the recipe baseline

    def test_none_when_baseline_area_none(self):
        self.assertIsNone(resource_growth_ratio(RECIPE_BEST, None))
        self.assertIsNone(resource_growth_ratio(RECIPE_BEST, {}))

    def test_none_when_cand_area_none(self):
        self.assertIsNone(resource_growth_ratio(None, RECIPE_BEST))

    def test_none_when_baseline_area_zero(self):
        # All counts zero -> baseline area 0.0 -> no meaningful ratio.
        baseline = {"lut": 0, "ff": 0, "part": "xc7z020-clg400-1"}
        self.assertEqual(area_score(baseline), 0.0)
        self.assertIsNone(resource_growth_ratio(RECIPE_BEST, baseline))


if __name__ == "__main__":
    unittest.main()
