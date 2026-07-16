"""Offline unit tests for the HARPO core logic.

Pure stdlib `unittest`. No Vitis, no LLM, no network — exercises budget policy,
candidate scoring, the diagnosis engine, the interface-contract checker, and the
deterministic RecipeProvider. Run either way::

    python3 -m unittest tests.test_core -v
    python3 tests/test_core.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

# Allow `python3 tests/test_core.py` (repo root not on sys.path otherwise).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harpo.budget import BudgetManager
from harpo.candidate import best, correctness_tier, score
from harpo.diagnosis import diagnose, diagnose_csynth
from harpo.models import Candidate
from harpo.patch_engine import check_contract
from harpo.recipes import RecipeProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_candidate(cid="c", *, csim_pass=False, csynth_pass=False,
                   csynth_metrics=None, diagnosis_history=None):
    """Build a Candidate directly with dummy paths (no real dirs needed)."""
    return Candidate(
        candidate_id=cid,
        workdir=Path("/tmp/nonexistent") / cid,
        src_dir=Path("/tmp/nonexistent") / cid / "src",
        csim_pass=csim_pass,
        csynth_pass=csynth_pass,
        csynth_metrics=csynth_metrics,
        diagnosis_history=list(diagnosis_history or []),
    )


# ---------------------------------------------------------------------------
# 1) BudgetManager
# ---------------------------------------------------------------------------
class TestBudgetManager(unittest.TestCase):
    def test_missing_limit_is_unlimited(self):
        bm = BudgetManager({"limits": {"csim": 5}})
        # csynth has no configured limit -> infinite.
        self.assertEqual(bm.remaining("csynth"), float("inf"))
        self.assertTrue(bm.can("csynth"))
        for _ in range(1000):
            bm.spend("csynth")
        self.assertTrue(bm.can("csynth"))

    def test_can_spend_remaining_with_reserve(self):
        # limit 5, reserve 1 held back -> 4 usable non-reserved invocations.
        bm = BudgetManager({
            "limits": {"csim": 5},
            "reserve": {"final_csim": 1},
        })
        self.assertEqual(bm.remaining("csim"), 4)
        for i in range(4):
            self.assertTrue(bm.can("csim"), f"csim should be affordable at {i}")
            bm.spend("csim")
        # 4 spent, reserve holds the 5th back -> no more non-reserved spend.
        self.assertEqual(bm.remaining("csim"), 0)
        self.assertFalse(bm.can("csim"))
        # remaining math after spending.
        self.assertEqual(bm.spent["csim"], 4)

    def test_remaining_without_reserve(self):
        bm = BudgetManager({"limits": {"llm_calls": 3}})
        self.assertEqual(bm.remaining("llm_calls"), 3)
        bm.spend("llm_calls")
        self.assertEqual(bm.remaining("llm_calls"), 2)

    def test_snapshot_serializable(self):
        bm = BudgetManager({"limits": {"csim": 5}})
        bm.spend("csynth")  # unlimited action
        snap = bm.snapshot()
        # inf limits map to None in the snapshot; only configured limits appear.
        self.assertEqual(snap["limits"], {"csim": 5})
        self.assertEqual(snap["spent"], {"csynth": 1})
        self.assertIsInstance(snap["reserve"], dict)

    def test_exhausted_only_when_no_csim_and_no_llm(self):
        # csim still available -> not exhausted.
        bm = BudgetManager({"limits": {"csim": 1, "llm_calls": 0}})
        self.assertFalse(bm.exhausted())
        bm.spend("csim")
        # now csim exhausted AND llm_calls is 0 -> exhausted.
        self.assertFalse(bm.can("csim"))
        self.assertFalse(bm.can("llm_calls"))
        self.assertTrue(bm.exhausted())

        # llm still available keeps us alive even with csim gone.
        bm2 = BudgetManager({"limits": {"csim": 0, "llm_calls": 2}})
        self.assertFalse(bm2.exhausted())

    def test_policy_allows_budget_exhausted_blocks(self):
        bm = BudgetManager({"limits": {"csim": 0}})
        ok, reason = bm.policy_allows(
            "csim", csim_pass=False, regressed=False, repeated=False)
        self.assertFalse(ok)
        self.assertIn("budget exhausted", reason)

    def test_policy_allows_no_csynth_cosim_before_csim_pass(self):
        bm = BudgetManager({"limits": {"csynth": 5, "cosim": 5}})
        ok, reason = bm.policy_allows(
            "csynth", csim_pass=False, regressed=False, repeated=False)
        self.assertFalse(ok)
        self.assertIn("csim", reason)

        ok, reason = bm.policy_allows(
            "cosim", csim_pass=False, regressed=False, repeated=False)
        self.assertFalse(ok)
        self.assertIn("csim", reason)

        # once csim passes, csynth is allowed.
        ok, _ = bm.policy_allows(
            "csynth", csim_pass=True, regressed=False, repeated=False)
        self.assertTrue(ok)

    def test_policy_allows_regressed_or_repeated_blocks_llm(self):
        bm = BudgetManager({"limits": {"llm_calls": 5}})
        ok, reason = bm.policy_allows(
            "llm_calls", csim_pass=True, regressed=True, repeated=False)
        self.assertFalse(ok)
        self.assertIn("stop/rollback", reason)

        ok, reason = bm.policy_allows(
            "llm_calls", csim_pass=True, regressed=False, repeated=True)
        self.assertFalse(ok)
        self.assertIn("stop/rollback", reason)

    def test_policy_allows_clean_case_ok(self):
        bm = BudgetManager({"limits": {"llm_calls": 5, "csim": 5}})
        ok, reason = bm.policy_allows(
            "llm_calls", csim_pass=True, regressed=False, repeated=False)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_policy_ordering_budget_before_stage(self):
        # budget check fires before stage-ordering: csynth with no budget AND no
        # csim pass should report the budget reason (budget is checked first).
        bm = BudgetManager({"limits": {"csynth": 0}})
        ok, reason = bm.policy_allows(
            "csynth", csim_pass=False, regressed=False, repeated=False)
        self.assertFalse(ok)
        self.assertIn("budget exhausted", reason)


# ---------------------------------------------------------------------------
# 2) candidate.score / best
# ---------------------------------------------------------------------------
class TestCandidateScoring(unittest.TestCase):
    def test_correctness_tier(self):
        self.assertEqual(correctness_tier(make_candidate()), 0)
        self.assertEqual(
            correctness_tier(make_candidate(csim_pass=True)), 1)
        self.assertEqual(
            correctness_tier(
                make_candidate(csim_pass=True, csynth_pass=True)), 2)

    def test_tier1_beats_tier0(self):
        t0 = make_candidate("t0")
        t1 = make_candidate("t1", csim_pass=True)
        self.assertIs(best([t0, t1]), t1)
        self.assertIs(best([t1, t0]), t1)

    def test_tier2_beats_tier1_regardless_of_ppa(self):
        # tier-1 with great PPA vs tier-2 with terrible PPA: tier-2 wins.
        t1 = make_candidate(
            "t1", csim_pass=True,
            csynth_metrics={"ii": 1, "latency_worst": 10, "lut": 100})
        t2 = make_candidate(
            "t2", csim_pass=True, csynth_pass=True,
            csynth_metrics={"ii": 99, "latency_worst": 9999, "lut": 99999})
        self.assertIs(best([t1, t2]), t2)

    def test_within_tier_lower_interval_wins(self):
        # Throughput is now scored on interval_max, not per-loop ii.
        a = make_candidate("a", csim_pass=True, csynth_pass=True,
                           csynth_metrics={"interval_max": 1024})
        b = make_candidate("b", csim_pass=True, csynth_pass=True,
                           csynth_metrics={"interval_max": 256})
        for c in (a, b):
            c.objective = "speed_first"
        self.assertIs(best([a, b]), b)

    def test_within_tier_lower_latency_breaks_interval_tie(self):
        a = make_candidate("a", csim_pass=True, csynth_pass=True,
                           csynth_metrics={"interval_max": 256, "latency_worst": 500})
        b = make_candidate("b", csim_pass=True, csynth_pass=True,
                           csynth_metrics={"interval_max": 256, "latency_worst": 200})
        for c in (a, b):
            c.objective = "speed_first"
        self.assertIs(best([a, b]), b)

    def test_within_tier_lower_area_breaks_throughput_tie(self):
        # speed_first: after interval_max + latency tie, lower area_score wins
        # (smaller LUT -> smaller normalized utilization). Needs a known part
        # so area_score can normalize.
        a = make_candidate(
            "a", csim_pass=True, csynth_pass=True,
            csynth_metrics={"interval_max": 256, "latency_worst": 200,
                            "lut": 5000, "part": "xc7z020-clg400-1"})
        b = make_candidate(
            "b", csim_pass=True, csynth_pass=True,
            csynth_metrics={"interval_max": 256, "latency_worst": 200,
                            "lut": 3000, "part": "xc7z020-clg400-1"})
        for c in (a, b):
            c.objective = "speed_first"
        self.assertIs(best([a, b]), b)

    def test_missing_metrics_no_crash(self):
        # No csynth_metrics at all -> scoring must not raise and best() works.
        a = make_candidate("a", csim_pass=True, csynth_pass=True,
                           csynth_metrics=None)
        b = make_candidate("b", csim_pass=True, csynth_pass=True,
                           csynth_metrics={"ii": 5})
        s = score(a)
        self.assertIsInstance(s, tuple)
        self.assertIsNotNone(best([a, b]))

    def test_score_cached_on_candidate(self):
        c = make_candidate("c", csim_pass=True)
        s = score(c)
        self.assertEqual(c.score, s)

    def test_best_empty_is_none(self):
        self.assertIsNone(best([]))


# ---------------------------------------------------------------------------
# 3) diagnose (csim era)
# ---------------------------------------------------------------------------
class TestDiagnose(unittest.TestCase):
    def test_status_mapping(self):
        cases = {
            "pass": ("PASS", "none"),
            "compile_error": ("COMPILE_ERROR", "minimal_compile_fix"),
            "functional_fail": ("CSIM_FUNCTIONAL_FAIL",
                                "minimal_functional_patch"),
            "timeout": ("TIMEOUT_OR_DEADLOCK", "fix_loop_or_protocol"),
            "tool_unavailable": ("TOOL_UNAVAILABLE", "none"),
        }
        for status, (klass, action) in cases.items():
            d = diagnose({"status": status})
            self.assertEqual(d.klass, klass, status)
            self.assertEqual(d.recommended_action, action, status)

    def test_unknown_status_falls_back(self):
        d = diagnose({"status": "something_weird"})
        self.assertEqual(d.klass, "UNKNOWN")
        self.assertEqual(d.recommended_action, "rollback_or_escalate")

    def test_repeated_failure_escalates(self):
        d = diagnose(
            {"status": "compile_error"}, history=["COMPILE_ERROR"])
        self.assertTrue(d.repeated)
        self.assertEqual(d.recommended_action, "rollback_or_escalate")

    def test_pass_does_not_escalate_on_repeat(self):
        d = diagnose({"status": "pass"}, history=["PASS"])
        self.assertTrue(d.repeated)
        self.assertEqual(d.recommended_action, "none")

    def test_tool_unavailable_does_not_escalate_on_repeat(self):
        d = diagnose(
            {"status": "tool_unavailable"}, history=["TOOL_UNAVAILABLE"])
        self.assertTrue(d.repeated)
        self.assertEqual(d.recommended_action, "none")

    def test_evidence_includes_errors_and_summary(self):
        d = diagnose({"status": "compile_error", "errors": ["err line A"]})
        self.assertIn("err line A", d.evidence)
        self.assertIn("compilation failed", d.evidence)


# ---------------------------------------------------------------------------
# 4) diagnose_csynth
# ---------------------------------------------------------------------------
class TestDiagnoseCsynth(unittest.TestCase):
    def test_pass_timing_resource_route_to_optimize(self):
        for status in ("pass", "timing_fail", "resource_overuse"):
            d = diagnose_csynth({"status": status})
            self.assertEqual(
                d.recommended_action, "optimize_ppa", status)

    def test_synthesis_fail_routes_to_repair(self):
        d = diagnose_csynth({"status": "synthesis_fail"})
        self.assertEqual(d.klass, "SYNTHESIS_FAIL")
        self.assertEqual(d.recommended_action, "fix_loop_or_protocol")

    def test_evidence_includes_ppa_metric_line(self):
        metrics = {
            "ii": 4, "depth": 12, "latency_worst": 100,
            "clock_target_ns": 10, "clock_estimated_ns": 8, "fmax_mhz": 125,
            "lut": 500, "util_lut": 2, "ff": 600, "util_ff": 3,
            "dsp": 4, "util_dsp": 1, "bram_18k": 2, "util_bram": 1,
        }
        d = diagnose_csynth({"status": "pass", "metrics": metrics})
        joined = "\n".join(d.evidence)
        self.assertIn("II=4", joined)
        self.assertIn("latency_worst=100", joined)
        self.assertIn("LUT=500", joined)

    def test_evidence_falls_back_when_no_metrics(self):
        d = diagnose_csynth({"status": "pass"})
        self.assertTrue(d.evidence)  # non-empty fallback line
        self.assertIn("csynth status", d.evidence[0])


# ---------------------------------------------------------------------------
# 5) check_contract
# ---------------------------------------------------------------------------
ORIGINAL_KERNEL = """\
#include "vadd.h"

void vadd(const int a[N], const int b[N], int out[N]) {
    for (int i = 0; i < N; i++) {
        out[i] = a[i] + b[i];
    }
}
"""


class TestCheckContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src_dir = Path(self.tmp.name)
        (self.src_dir / "vadd.cpp").write_text(ORIGINAL_KERNEL)

    def tearDown(self):
        self.tmp.cleanup()

    def _task(self, **overrides):
        base = dict(
            top_function="vadd",
            tb_files=[Path("tb/tb_vadd.cpp")],
            policy={},
            src_dir=self.src_dir,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def _proposal(self, target_file, whole_file):
        return SimpleNamespace(
            target_file=target_file, whole_file=whole_file)

    def test_rejects_testbench_target(self):
        task = self._task()
        prop = self._proposal("tb_vadd.cpp", "anything")
        ok, reasons = check_contract(task, prop, "anything")
        self.assertFalse(ok)
        self.assertTrue(any("testbench" in r for r in reasons))

    def test_rejects_out_of_glob_target(self):
        # Restrict allowed globs so a non-matching path is rejected.
        task = self._task(policy={"allowed_edit_globs": ["kernels/*.cpp"]})
        prop = self._proposal("vadd.cpp", ORIGINAL_KERNEL)
        ok, reasons = check_contract(task, prop, ORIGINAL_KERNEL)
        self.assertFalse(ok)
        self.assertTrue(any("allowed_edit_globs" in r for r in reasons))

    def test_rejects_top_function_param_count_change(self):
        # Drop a parameter -> 3 -> 2, signature change must be rejected.
        changed = ORIGINAL_KERNEL.replace(
            "void vadd(const int a[N], const int b[N], int out[N]) {",
            "void vadd(const int a[N], int out[N]) {")
        task = self._task()
        prop = self._proposal("vadd.cpp", changed)
        ok, reasons = check_contract(task, prop, changed)
        self.assertFalse(ok)
        self.assertTrue(any("parameter count changed" in r for r in reasons))

    def test_accepts_clean_pragma_only_edit(self):
        # Same signature, only a pragma added inside the body -> accepted.
        patched = ORIGINAL_KERNEL.replace(
            "for (int i = 0; i < N; i++) {",
            "for (int i = 0; i < N; i++) {\n        #pragma HLS PIPELINE II=1")
        task = self._task()
        prop = self._proposal("vadd.cpp", patched)
        ok, reasons = check_contract(task, prop, patched)
        self.assertTrue(ok, reasons)
        self.assertEqual(reasons, [])

    def test_accepts_edit_to_non_top_file(self):
        # A multi-file design's helper unit never names the top function; an
        # edit there must NOT be rejected for "top missing" (first seen on
        # lns_mac_001: every add_unit.cpp proposal bounced on this).
        helper = "int helper(int x) { return x + 1; }\n"
        (self.src_dir / "helper.cpp").write_text(helper)
        patched = helper.replace("x + 1", "x + 2")
        task = self._task()
        prop = self._proposal("helper.cpp", patched)
        ok, reasons = check_contract(task, prop, patched)
        self.assertTrue(ok, reasons)
        self.assertEqual(reasons, [])

    def test_still_rejects_top_removed_from_top_file(self):
        # The guard on the file that DOES define the top stays intact: a
        # patch that drops the top function from vadd.cpp is rejected.
        task = self._task()
        prop = self._proposal("vadd.cpp", "// everything deleted\n")
        ok, reasons = check_contract(task, prop, "// everything deleted\n")
        self.assertFalse(ok)
        self.assertTrue(any("missing from patched file" in r for r in reasons))


# ---------------------------------------------------------------------------
# 6) RecipeProvider
# ---------------------------------------------------------------------------
# A fixed-size array-arg kernel with an outer and inner loop.
RECIPE_KERNEL = """\
#include "mac8.h"

void mac8(const int in[IN_SIZE], const int w[W_SIZE], int out[OUT_SIZE]) {
    for (int i = 0; i < N; i++) {
        int acc = 0;
        for (int k = 0; k < 8; k++) {
            acc += in[i * 8 + k] * w[k];
        }
        out[i] = acc;
    }
}
"""


class TestRecipeProvider(unittest.TestCase):
    def _task(self):
        return SimpleNamespace(top_function="mac8")

    def _optimize_diag(self):
        return SimpleNamespace(
            recommended_action="optimize_ppa",
            klass="PASS",
            evidence=[])

    def _sources(self, text=RECIPE_KERNEL):
        return {"mac8.cpp": text}

    def test_abstains_when_not_optimize(self):
        rp = RecipeProvider()
        diag = SimpleNamespace(
            recommended_action="minimal_compile_fix", klass="COMPILE_ERROR",
            evidence=[])
        self.assertIsNone(rp.propose(self._task(), self._sources(), diag, []))

    def test_first_proposal_is_well_formed_array_partition(self):
        rp = RecipeProvider()
        prop = rp.propose(
            self._task(), self._sources(), self._optimize_diag(), [])
        self.assertIsNotNone(prop)
        whole = prop.whole_file
        self.assertIn("ARRAY_PARTITION", whole)
        # Precise form: a partition TYPE keyword + factor= + dim=.
        self.assertTrue(
            ("cyclic" in whole) or ("block" in whole),
            "partition must carry a type keyword")
        self.assertIn("factor=", whole)
        self.assertIn("dim=", whole)

    def test_successive_calls_advance_then_exhaust(self):
        rp = RecipeProvider()
        diag = self._optimize_diag()
        src = self._sources()
        proposals = []
        for _ in range(100):
            p = rp.propose(self._task(), src, diag, [])
            if p is None:
                break
            proposals.append(p)
        # Several distinct recipes get proposed before exhaustion.
        self.assertGreater(len(proposals), 1)
        # Eventually returns None (worklist exhausted).
        self.assertIsNone(rp.propose(self._task(), src, diag, []))
        # Distinct edit plans across the run (cursor really advances).
        plans = {p.edit_plan for p in proposals}
        self.assertGreater(len(plans), 1)

    def test_already_present_recipe_is_skipped_no_duplicate(self):
        # Pre-insert the highest-priority cyclic factor=8 partition on `in`.
        pragma = ("#pragma HLS ARRAY_PARTITION variable=in "
                  "cyclic factor=8 dim=1")
        seeded = RECIPE_KERNEL.replace(
            "void mac8(const int in[IN_SIZE], const int w[W_SIZE], "
            "int out[OUT_SIZE]) {",
            "void mac8(const int in[IN_SIZE], const int w[W_SIZE], "
            "int out[OUT_SIZE]) {\n    " + pragma)
        src = {"mac8.cpp": seeded}
        rp = RecipeProvider()
        for _ in range(100):
            p = rp.propose(self._task(), src, self._optimize_diag(), [])
            if p is None:
                break
            # The provider de-dups verbatim: a recipe already present in the
            # source is never inserted a SECOND time, so the seeded pragma must
            # still appear exactly once in any emitted whole_file (the original
            # occurrence carried through, never a duplicate).
            self.assertEqual(
                p.whole_file.count(pragma), 1,
                "the already-present pragma must never be inserted a 2nd time")


if __name__ == "__main__":
    unittest.main(verbosity=2)
