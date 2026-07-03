"""Tests for the recipe-only capped throughput-target probe.

Two layers:

  * Unit tests for :func:`harpo.probe.select_target` — the PURE selector
    (the testable core): baseline-only, an in-cap improving candidate, an
    over-area-cap candidate (excluded), an unknown-baseline-interval case, and
    defensive empty/None inputs.

  * One HERMETIC integration test (NO Vitis, NO LLM) that mirrors
    ``tests/test_optimize_safety.py``: csim runs FOR REAL on the gpp backend,
    while ``agent._run_csynth`` is monkeypatched to return canned metrics that
    make a recipe candidate a clear in-cap winner. It asserts
    ``derive_throughput_target`` returns that candidate's interval_max and that
    ``probe_log`` shows 0 tokens / recipe-only.

Pure stdlib ``unittest``::

    python3 -m unittest tests.test_probe -v
    python3 tests/test_probe.py
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Allow `python3 tests/test_probe.py` (repo root not on sys.path).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harpo import agent, probe, store
from harpo.budget import BudgetManager
from harpo.probe import derive_throughput_target, select_target
from harpo.task import load_task

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_DIR = REPO_ROOT / "tasks" / "mac8_001"


# Capacities matching the area.py fallback so area_score is well-defined for the
# canned metrics below (part resolves to the xc7z020 table).
_PART = "xc7z020-clg400-1"


def _metrics(interval_max, lut, ff=0):
    """A minimal csynth metrics dict that area_score can score."""
    return {
        "part": _PART,
        "interval_max": interval_max,
        "latency_worst": interval_max,
        "ii": 1,
        "lut": lut,
        "ff": ff,
        "dsp": 0,
        "bram_18k": 0,
        "uram": 0,
    }


class SelectTargetUnitTest(unittest.TestCase):
    """Exhaustive unit tests for the pure selector."""

    def test_baseline_only_returns_baseline_interval(self):
        base = _metrics(1024, lut=300)
        self.assertEqual(select_target(base, []), 1024.0)

    def test_improving_in_cap_candidate_wins(self):
        base = _metrics(1024, lut=300)        # area_score ~ 300/53200
        cand = {
            "interval_max": 256,
            # ~2x area, exactly at the cap -> still qualifies (<=).
            "area_score": 2.0 * (300 / 53200),
            "csim_pass": True,
            "csynth_pass": True,
        }
        self.assertEqual(select_target(base, [cand], area_cap=2.0), 256.0)

    def test_improving_but_too_large_is_excluded(self):
        base = _metrics(1024, lut=300)
        from harpo.area import area_score
        base_area = area_score(base)
        over = {
            "interval_max": 64,                     # much faster ...
            "area_score": 2.5 * base_area,          # ... but over the 2.0x cap
            "csim_pass": True,
            "csynth_pass": True,
        }
        # Excluded by area cap -> falls back to baseline interval.
        self.assertEqual(select_target(base, [over], area_cap=2.0), 1024.0)

    def test_lowest_among_several_qualifiers(self):
        base = _metrics(1024, lut=300)
        from harpo.area import area_score
        ba = area_score(base)
        cands = [
            {"interval_max": 512, "area_score": 1.2 * ba,
             "csim_pass": True, "csynth_pass": True},
            {"interval_max": 256, "area_score": 1.8 * ba,
             "csim_pass": True, "csynth_pass": True},
            {"interval_max": 32, "area_score": 5.0 * ba,   # over cap -> excluded
             "csim_pass": True, "csynth_pass": True},
        ]
        self.assertEqual(select_target(base, cands, area_cap=2.0), 256.0)

    def test_failing_candidates_are_ignored(self):
        base = _metrics(1024, lut=300)
        cands = [
            {"interval_max": 100, "area_score": 0.001,
             "csim_pass": False, "csynth_pass": True},   # csim fail
            {"interval_max": 120, "area_score": 0.001,
             "csim_pass": True, "csynth_pass": False},   # csynth fail
        ]
        self.assertEqual(select_target(base, cands, area_cap=2.0), 1024.0)

    def test_none_interval_baseline_returns_none(self):
        base = _metrics(None, lut=300)
        good = {"interval_max": 64, "area_score": 0.001,
                "csim_pass": True, "csynth_pass": True}
        self.assertIsNone(select_target(base, [good]))

    def test_defensive_none_and_empty(self):
        self.assertIsNone(select_target(None, []))
        self.assertIsNone(select_target({}, []))
        # Candidate with a None interval is simply skipped.
        base = _metrics(500, lut=100)
        self.assertEqual(
            select_target(base, [{"interval_max": None, "area_score": 0.0,
                                  "csim_pass": True, "csynth_pass": True}]),
            500.0,
        )

    def test_no_area_info_does_not_block_a_faster_candidate(self):
        # If neither side has area, the cap can't be enforced -> faster wins.
        base = {"interval_max": 1000}
        cand = {"interval_max": 200, "area_score": None,
                "csim_pass": True, "csynth_pass": True}
        self.assertEqual(select_target(base, [cand]), 200.0)


class DeriveTargetHermeticTest(unittest.TestCase):
    """End-to-end probe: real gpp csim, canned (monkeypatched) csynth.

    Mirrors test_optimize_safety: csim runs for real so applied recipe
    candidates are honestly re-verified; csynth is canned so no Vitis is needed.
    The canned metrics make the FIRST applicable recipe candidate a clear
    in-cap throughput winner, so the derived target is that candidate's
    interval_max (lower than baseline) — proving the probe DERIVES a ceiling.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="harpo_probe_")
        self._orig_repo_root = store.REPO_ROOT
        store.REPO_ROOT = Path(self._tmp)
        self.addCleanup(self._restore_repo_root)
        self.addCleanup(shutil.rmtree, self._tmp, True)

        # Monkeypatch agent._run_csynth: the FIRST synth call is the baseline
        # (slow, small area); every later call is an applied recipe candidate
        # (fast, modest area -> in-cap winner). csim is left untouched (real g++).
        self._orig_run_csynth = agent._run_csynth
        self._synth_calls = 0

        def fake_run_csynth(cm, cand, task, budget, backend, events):
            budget.spend("csynth")
            self._synth_calls += 1
            if self._synth_calls == 1:
                m = _metrics(1024, lut=300)        # baseline: slow
            else:
                m = _metrics(256, lut=450)         # candidate: faster, ~1.5x area
            cs = {"status": "pass", "pass": True, "metrics": m}
            cand.csynth_status = "pass"
            cand.csynth_pass = True
            cand.csynth_metrics = m
            return cs

        agent._run_csynth = fake_run_csynth
        self.addCleanup(self._restore_run_csynth)

        # Load mac8 (its spec now ships a target) and FORCE no target so the
        # probe path is exercised.
        self.task = dataclasses.replace(
            load_task(TASK_DIR), throughput_target=None)

    def _restore_repo_root(self):
        store.REPO_ROOT = self._orig_repo_root

    def _restore_run_csynth(self):
        agent._run_csynth = self._orig_run_csynth

    def test_probe_derives_candidate_interval_recipe_only(self):
        if shutil.which(os.environ.get("CXX") or "") is None and not any(
            shutil.which(c) for c in ("g++", "clang++", "c++")
        ):
            self.skipTest("no C++ compiler available; gpp csim cannot run")

        budget = BudgetManager(self.task.budget)
        target, log = derive_throughput_target(
            self.task, budget=budget, csim_backend="gpp",
            synth_backend="vitis_hls", max_synth=4, area_cap=2.0)

        # (a) the probe derived the in-cap candidate's interval (256 < 1024).
        self.assertEqual(target, 256.0)
        self.assertEqual(log["baseline_interval_max"], 1024.0)
        self.assertFalse(log["fell_back_to_baseline"])

        # (b) at least one recipe candidate was actually applied + measured.
        applied = [t for t in log["tried"] if t.get("applied")]
        self.assertTrue(applied, "expected >=1 applied recipe probe candidate")
        winner = [t for t in applied if t.get("interval_max") == 256.0]
        self.assertTrue(winner, "the in-cap candidate must be recorded")

        # (c) ZERO LLM tokens — recipe-only path.
        self.assertEqual(log["tokens"], 0)

        # (d) honest budget accounting: >=2 csynth (baseline + >=1 candidate).
        self.assertGreaterEqual(budget.spent.get("csynth", 0), 2)
        self.assertGreaterEqual(budget.spent.get("csim", 0), 2)

    def test_probe_never_raises_on_full_failure(self):
        # A blown-up probe must degrade to (baseline_or_None, log), never raise.
        # Force a hard failure inside the probe by removing csim budget so the
        # baseline never runs -> returns (None, log) cleanly.
        empty_budget = BudgetManager(
            {"mode": "per_tool", "limits": {"csim": 0, "csynth": 0}})
        target, log = derive_throughput_target(
            self.task, budget=empty_budget, csim_backend="gpp")
        self.assertIsNone(target)
        self.assertIsInstance(log, dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
