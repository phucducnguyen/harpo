"""Offline unit tests for the per-task OBJECTIVE knob.

Pure stdlib `unittest`. No Vitis, no LLM, no network. Verifies the new
objective enum (speed_first | area_first | adp | satisfice_then_area |
pareto_report), that throughput is scored on the design-level ``interval_max``
(NOT per-loop ``ii`` — the metric-bug regression), that satisfice_then_area
meets a target before minimizing area (the policy-bug fix), and that
``load_task`` reads the spec key tolerantly (incl. legacy aliases). Run::

    python3 -m unittest tests.test_objective -v
    python3 tests/test_objective.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Allow `python3 tests/test_objective.py` (repo root not on sys.path otherwise).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harpo.candidate import best, pareto_front, score
from harpo.models import Candidate
from harpo.task import load_task

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_candidate(cid, *, objective="speed_first", throughput_target=None,
                   csynth_metrics=None, steps=0):
    """Build a tier-2 Candidate directly with dummy paths (no real dirs needed)."""
    return Candidate(
        candidate_id=cid,
        workdir=Path("/tmp/nonexistent") / cid,
        src_dir=Path("/tmp/nonexistent") / cid / "src",
        csim_pass=True,
        csynth_pass=True,
        csynth_metrics=csynth_metrics,
        objective=objective,
        throughput_target=throughput_target,
        diagnosis_history=["X"] * steps,
    )


# Metrics carry capacities so area.area_score() can normalize utilizations.
# Picking a small part keeps the math simple; only relative area matters here.
CAPS = {
    "avail_lut": 100000, "avail_ff": 200000, "avail_dsp": 1000,
    "avail_bram": 500, "avail_uram": 100, "part": "xczu",
}


def metrics(interval_max=None, latency_worst=None, ii=None, lut=0, **extra):
    m = dict(CAPS)
    m.update(interval_max=interval_max, latency_worst=latency_worst, ii=ii, lut=lut)
    m.update(extra)
    return m


class TestSpeedFirst(unittest.TestCase):
    def test_lower_interval_max_wins(self):
        lo = make_candidate("LO", objective="speed_first",
                            csynth_metrics=metrics(interval_max=1, latency_worst=518, lut=573))
        hi = make_candidate("HI", objective="speed_first",
                            csynth_metrics=metrics(interval_max=4, latency_worst=260, lut=706))
        self.assertGreater(score(lo), score(hi))  # interval_max wins -> LO
        self.assertEqual(best([hi, lo]).candidate_id, "LO")

    def test_unrolled_none_ii_with_worse_interval_max_loses(self):
        """REGRESSION (metric bug): an over-unrolled candidate reports ii=None
        but a WORSE interval_max. Scoring on interval_max must make it LOSE to
        a candidate with a real ii and a better (lower) interval_max."""
        good = make_candidate("GOOD", objective="speed_first",
                             csynth_metrics=metrics(interval_max=1024, ii=1, lut=573))
        unrolled = make_candidate("UNROLLED", objective="speed_first",
                                csynth_metrics=metrics(interval_max=3073, ii=None, lut=9000))
        self.assertGreater(score(good), score(unrolled))
        self.assertEqual(best([unrolled, good]).candidate_id, "GOOD")


class TestAreaFirst(unittest.TestCase):
    def test_prefers_smaller_area_when_throughput_ties(self):
        small = make_candidate("SMALL", objective="area_first",
                             csynth_metrics=metrics(interval_max=10, lut=500))
        big = make_candidate("BIG", objective="area_first",
                           csynth_metrics=metrics(interval_max=10, lut=5000))
        self.assertGreater(score(small), score(big))
        self.assertEqual(best([big, small]).candidate_id, "SMALL")


class TestSatisficeThenArea(unittest.TestCase):
    def test_meeter_with_larger_area_beats_misser_that_is_smaller(self):
        """CORE POLICY: a candidate that MEETS the throughput target but is
        larger beats one that MISSES the target even though it is smaller."""
        meeter_big = make_candidate("MEET_BIG", objective="satisfice_then_area",
                                  throughput_target=1024,
                                  csynth_metrics=metrics(interval_max=1024, lut=5000))
        misser_small = make_candidate("MISS_SMALL", objective="satisfice_then_area",
                                    throughput_target=1024,
                                    csynth_metrics=metrics(interval_max=2048, lut=500))
        self.assertGreater(score(meeter_big), score(misser_small))
        self.assertEqual(best([misser_small, meeter_big]).candidate_id, "MEET_BIG")

    def test_among_meeters_smaller_area_wins(self):
        """CORE POLICY: among candidates that all meet the target, the smaller
        one wins."""
        small = make_candidate("SMALL", objective="satisfice_then_area",
                             throughput_target=1024,
                             csynth_metrics=metrics(interval_max=1000, lut=500))
        big = make_candidate("BIG", objective="satisfice_then_area",
                           throughput_target=1024,
                           csynth_metrics=metrics(interval_max=900, lut=5000))
        # Both meet target; BIG is even faster but much larger -> SMALL wins.
        self.assertGreater(score(small), score(big))
        self.assertEqual(best([big, small]).candidate_id, "SMALL")

    def test_no_target_degrades_to_throughput_first(self):
        """With no usable target, satisfice_then_area orders by throughput
        (lower interval_max) first."""
        fast = make_candidate("FAST", objective="satisfice_then_area",
                            throughput_target=None,
                            csynth_metrics=metrics(interval_max=100, lut=5000))
        slow = make_candidate("SLOW", objective="satisfice_then_area",
                            throughput_target=None,
                            csynth_metrics=metrics(interval_max=500, lut=500))
        self.assertGreater(score(fast), score(slow))
        self.assertEqual(best([slow, fast]).candidate_id, "FAST")


class TestCorrectnessDominates(unittest.TestCase):
    def test_tier_dominates_ppa(self):
        # A tier-1 (csim only) candidate never outranks a tier-2 one,
        # however much better its PPA looks.
        tier2 = make_candidate("T2", objective="speed_first",
                             csynth_metrics=metrics(interval_max=9999, lut=9999))
        tier1 = Candidate(
            candidate_id="T1",
            workdir=Path("/tmp/x/T1"), src_dir=Path("/tmp/x/T1/src"),
            csim_pass=True, csynth_pass=False,
            csynth_metrics=metrics(interval_max=1, lut=1),
            objective="speed_first",
        )
        self.assertGreater(score(tier2), score(tier1))


class TestParetoFront(unittest.TestCase):
    def test_non_dominated_only(self):
        # A: fast+small (on front). B: slow+big (dominated by A). C: slow+small,
        # A: fast+big -> tradeoff, both on front against each other.
        a = make_candidate("A", csynth_metrics=metrics(interval_max=10, lut=500))
        b = make_candidate("B", csynth_metrics=metrics(interval_max=20, lut=5000))
        c = make_candidate("C", csynth_metrics=metrics(interval_max=5, lut=8000))
        front_ids = {x.candidate_id for x in pareto_front([a, b, c])}
        self.assertIn("A", front_ids)   # dominates B
        self.assertIn("C", front_ids)   # faster than A (tradeoff)
        self.assertNotIn("B", front_ids)

    def test_skips_missing_coords_and_non_passing(self):
        good = make_candidate("G", csynth_metrics=metrics(interval_max=10, lut=500))
        no_iv = make_candidate("NOIV", csynth_metrics=metrics(interval_max=None, lut=500))
        not_passing = Candidate(
            candidate_id="NP",
            workdir=Path("/tmp/x/NP"), src_dir=Path("/tmp/x/NP/src"),
            csim_pass=True, csynth_pass=False,
            csynth_metrics=metrics(interval_max=1, lut=1),
        )
        ids = {x.candidate_id for x in pareto_front([good, no_iv, not_passing])}
        self.assertEqual(ids, {"G"})


class TestDefaultDataclassObjective(unittest.TestCase):
    def test_default_is_satisfice_then_area(self):
        c = Candidate(
            candidate_id="C",
            workdir=Path("/tmp/x/C"), src_dir=Path("/tmp/x/C/src"),
            csim_pass=True, csynth_pass=True,
            csynth_metrics=metrics(interval_max=10, lut=500),
        )
        self.assertEqual(c.objective, "satisfice_then_area")
        self.assertIsNone(c.throughput_target)

    def test_to_dict_includes_new_fields(self):
        c = make_candidate("C", objective="area_first", throughput_target=1024,
                          csynth_metrics=metrics(interval_max=10, lut=500))
        d = c.to_dict()
        self.assertEqual(d["objective"], "area_first")
        self.assertEqual(d["throughput_target"], 1024)


class TestLoadTaskObjective(unittest.TestCase):
    def test_task_without_objective_defaults_to_satisfice(self):
        # A spec with neither "objective" nor "throughput_target" -> defaults.
        ctx = self._load()
        self.assertEqual(ctx.objective, "satisfice_then_area")
        self.assertIsNone(ctx.throughput_target)

    def _write_temp_task(self, tmp: Path, *, objective_value=None,
                         throughput_target=None):
        """Write a minimal valid task bundle; set keys only when provided."""
        (tmp / "src").mkdir(parents=True, exist_ok=True)
        (tmp / "tb").mkdir(parents=True, exist_ok=True)
        (tmp / "src" / "k.cpp").write_text("void k(){}\n")
        (tmp / "tb" / "tb_k.cpp").write_text("int main(){return 0;}\n")
        spec = {
            "task_id": "tmp_task",
            "top_function": "k",
            "entry_files": ["src/k.cpp"],
            "testbench_files": ["tb/tb_k.cpp"],
        }
        if objective_value is not None:
            spec["objective"] = objective_value
        if throughput_target is not None:
            spec["throughput_target"] = throughput_target
        (tmp / "spec.json").write_text(json.dumps(spec))

    def _load(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self._write_temp_task(tmp, **kw)
            return load_task(tmp)

    def test_explicit_valid_objective(self):
        self.assertEqual(self._load(objective_value="area_first").objective, "area_first")

    def test_case_insensitive(self):
        self.assertEqual(self._load(objective_value="Area_First").objective, "area_first")

    def test_legacy_throughput_maps_to_speed_first(self):
        self.assertEqual(self._load(objective_value="throughput").objective, "speed_first")

    def test_legacy_latency_maps_to_speed_first(self):
        self.assertEqual(self._load(objective_value="latency").objective, "speed_first")

    def test_unknown_falls_back_to_default(self):
        self.assertEqual(self._load(objective_value="minimize-area").objective,
                         "satisfice_then_area")

    def test_throughput_target_parsed_when_present(self):
        self.assertEqual(self._load(throughput_target=1024).throughput_target, 1024.0)

    def test_throughput_target_none_when_absent(self):
        self.assertIsNone(self._load().throughput_target)

    def test_throughput_target_none_when_non_numeric(self):
        self.assertIsNone(self._load(throughput_target="fast").throughput_target)


if __name__ == "__main__":
    unittest.main()
