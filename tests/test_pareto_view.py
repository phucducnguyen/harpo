"""Offline unit tests for the OPTIONAL Pareto/ADRS appendix view.

Pure stdlib `unittest`. No Vitis, no LLM, no network, no real run logs: we
exercise the pure geometry/ADRS helpers directly and assemble one tiny synthetic
log dir in a tempdir to confirm the renderer runs end-to-end without raising.

Asserts: dominance is computed correctly (a clearly-dominated point is flagged
off-frontier; a frontier point stays on it), and the ADRS helper returns 0 when
the query set equals the reference set and > 0 when strictly worse. Run::

    python3 -m unittest tests.test_pareto_view -v
    python3 tests/test_pareto_view.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Repo root + scripts/ on path so we can import both the metric lib and the view.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import pareto_view as pv  # noqa: E402

PART = "xc7z020-clg400-1"


def _metrics(interval_max, *, lut=800, ff=600, bram=2, dsp=4):
    return {
        "interval_max": interval_max, "latency_worst": interval_max * 8,
        "lut": lut, "ff": ff, "bram_18k": bram, "dsp": dsp, "part": PART,
    }


def _arm_log(baseline, best, *, tokens=0):
    return {
        "task_id": "mac8_001",
        "baseline_metrics": baseline,
        "best_metrics": best,
        "improved": best.get("interval_max") < baseline.get("interval_max"),
        "tokens": {"total_tokens": tokens},
        "candidates": [],
        "events": [],
    }


class DominanceTests(unittest.TestCase):
    def test_dominates_basic(self):
        # (256, 1.0) is <= on both and < on both -> dominates (512, 2.0).
        self.assertTrue(pv.dominates((256.0, 1.0), (512.0, 2.0)))
        # Reverse never holds.
        self.assertFalse(pv.dominates((512.0, 2.0), (256.0, 1.0)))
        # Equal on both -> no strict improvement -> not domination.
        self.assertFalse(pv.dominates((256.0, 1.0), (256.0, 1.0)))
        # Better on one, worse on the other -> neither dominates (a trade-off).
        self.assertFalse(pv.dominates((256.0, 2.0), (512.0, 1.0)))

    def test_pareto_flags_marks_dominated_point(self):
        # p0 dominates p2; p0 and p1 are mutual trade-offs (both on frontier).
        p0 = (256.0, 2.0)   # fast, big
        p1 = (1024.0, 0.5)  # slow, small
        p2 = (512.0, 3.0)   # dominated by p0 (slower AND bigger)
        flags = pv.pareto_flags([p0, p1, p2])
        self.assertEqual(flags, [True, True, False])

    def test_reference_set_dedups_and_drops_dominated(self):
        pts = [(256.0, 2.0), (256.0, 2.0), (512.0, 3.0), (1024.0, 0.5)]
        ref = pv.reference_set(pts)
        # Duplicate collapsed, dominated (512,3) dropped, two frontier pts left.
        self.assertEqual(sorted(ref), sorted([(256.0, 2.0), (1024.0, 0.5)]))


class AdrsTests(unittest.TestCase):
    def test_adrs_zero_when_query_equals_reference(self):
        ref = [(256.0, 2.0), (1024.0, 0.5)]
        # Query set covering the reference exactly -> distance 0 everywhere.
        self.assertAlmostEqual(pv.adrs(ref, ref), 0.0)
        # Single query point that IS one reference point still scores 0 on that
        # point; the other reference point pulls the mean above 0.
        self.assertAlmostEqual(pv.adrs([(256.0, 2.0)], [(256.0, 2.0)]), 0.0)

    def test_adrs_positive_when_strictly_worse(self):
        ref = [(256.0, 1.0)]
        worse = [(512.0, 2.0)]  # 2x worse on both coords
        d = pv.adrs(worse, ref)
        self.assertIsNotNone(d)
        self.assertGreater(d, 0.0)
        # Chebyshev relative distance: max(|512-256|/256, |2-1|/1) = max(1, 1) = 1.
        self.assertAlmostEqual(d, 1.0)

    def test_adrs_none_on_empty_or_degenerate(self):
        self.assertIsNone(pv.adrs([], [(1.0, 1.0)]))
        self.assertIsNone(pv.adrs([(1.0, 1.0)], []))
        # Reference point with a zero coordinate -> no usable relative distance.
        self.assertIsNone(pv.adrs([(1.0, 1.0)], [(0.0, 1.0)]))


class PointExtractionTests(unittest.TestCase):
    def test_point_defensive(self):
        self.assertIsNone(pv._point(None))
        self.assertIsNone(pv._point({}))
        self.assertIsNone(pv._point({"interval_max": True, "part": PART}))  # bool
        self.assertIsNone(pv._point({"lut": 800, "part": PART}))  # no interval_max
        pt = pv._point(_metrics(256))
        self.assertIsNotNone(pt)
        self.assertEqual(pt[0], 256.0)
        self.assertGreater(pt[1], 0.0)

    def test_kernel_points_baseline_shared_and_arms_mapped(self):
        base = _metrics(1024)
        recipe = _arm_log(base, _metrics(256))
        llm = _arm_log(base, _metrics(128, lut=9000))
        baseline, arm_pts = pv.kernel_points({"recipe": recipe, "llm": llm})
        self.assertIsNotNone(baseline)
        self.assertEqual(baseline[0], 1024.0)
        self.assertIn("recipe", arm_pts)
        self.assertIn("llm", arm_pts)
        self.assertEqual(arm_pts["recipe"][0], 256.0)


class RenderEndToEndTests(unittest.TestCase):
    def test_render_runs_on_synthetic_dir(self):
        base = _metrics(1024)
        with tempfile.TemporaryDirectory() as d:
            dpath = Path(d)
            (dpath / "mac8_001__recipe.json").write_text(
                json.dumps(_arm_log(base, _metrics(256))))
            (dpath / "mac8_001__llm.json").write_text(
                json.dumps(_arm_log(base, _metrics(128, lut=9000), tokens=4000)))
            # A deliberately malformed file must be skipped, not raise.
            (dpath / "junk__recipe.json").write_text("{ not json")

            from ablation_table import load_logs
            logs = load_logs(dpath)
            md = pv.render_markdown(logs)
        self.assertIn("Pareto / ADRS appendix", md)
        self.assertIn("mac8_001", md)
        self.assertIn("on-frontier?", md)
        self.assertIn("ADRS", md)


if __name__ == "__main__":
    unittest.main()
