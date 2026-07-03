"""Offline unit tests for the canonical ablation TABLE builder.

Pure stdlib `unittest`. No Vitis, no LLM, no network, no real run logs: we
synthesize a tiny canonical log dir (a couple of tasks, recipe + llm arms) into
a tempdir and exercise the builder's pure helpers + row assembly against it.

Asserts: category mapping, area_score/ADP computed via ``harpo.area``,
the Accepted mark derived from ``improved``, tokens 0 for recipe vs nonzero for
llm, and that the shared baseline row is de-duplicated (one per task). Run::

    python3 -m unittest tests.test_ablation_table -v
    python3 tests/test_ablation_table.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Repo root + scripts/ on path so we can import both the metric lib and builder.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from harpo.area import adp, area_score  # noqa: E402

import ablation_table as at  # noqa: E402

PART = "xc7z020-clg400-1"

# A shared baseline for matmul (both recipe + llm arms carry an identical copy).
BASELINE = {
    "interval_max": 512, "latency_worst": 4096, "lut": 800, "ff": 600,
    "bram_18k": 2, "dsp": 4, "part": PART,
}
RECIPE_BEST = {
    "interval_max": 256, "latency_worst": 2048, "lut": 900, "ff": 650,
    "bram_18k": 2, "dsp": 8, "part": PART,
}
LLM_BEST = {
    "interval_max": 128, "latency_worst": 1024, "lut": 9000, "ff": 700,
    "bram_18k": 2, "dsp": 16, "part": PART,
}


def _candidate(cid: str, metrics: dict, *, target=256.0,
               objective="satisfice_then_area") -> dict:
    return {
        "candidate_id": cid,
        "csim_pass": True,
        "csynth_pass": True,
        "csynth_metrics": metrics,
        "objective": objective,
        "throughput_target": target,
    }


def _log(task_id: str, *, baseline, best, best_id, improved, tokens,
         spent, target=256.0, objective="satisfice_then_area",
         probe=False) -> dict:
    events = []
    if probe:
        events.append({"event": "probe", "target": target,
                       "msg": "probe-derived"})
    return {
        "task_id": task_id,
        "phase": "optimize",
        "steps": 2,
        "baseline_metrics": baseline,
        "best_candidate": best_id,
        "best_metrics": best,
        "improved": improved,
        "budget": {"spent": spent},
        "tokens": {"prompt_tokens": tokens // 2, "completion_tokens": tokens // 2,
                   "total_tokens": tokens},
        "events": events,
        "candidates": [
            _candidate("cand_0000", baseline, target=target, objective=objective),
            _candidate(best_id, best, target=target, objective=objective),
        ],
    }


class _CanonicalDir:
    """Build a synthetic canonical/ dir of <task>__<arm>.json files."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        # matmul_001: recipe (no tokens, hand-set target) + llm (tokens).
        (self.dir / "matmul_001__recipe.json").write_text(json.dumps(_log(
            "matmul_001", baseline=BASELINE, best=RECIPE_BEST,
            best_id="cand_0001", improved=True, tokens=0,
            spent={"csim": 3, "csynth": 3, "llm_calls": 0})))
        (self.dir / "matmul_001__llm.json").write_text(json.dumps(_log(
            "matmul_001", baseline=BASELINE, best=LLM_BEST,
            best_id="cand_0001", improved=True, tokens=1234,
            spent={"csim": 4, "csynth": 4, "llm_calls": 6})))
        # gemm_001 (PolyBench): recipe arm only, no improvement (baseline kept).
        (self.dir / "gemm_001__recipe.json").write_text(json.dumps(_log(
            "gemm_001", baseline=BASELINE, best=BASELINE,
            best_id="cand_0000", improved=False, tokens=0,
            spent={"csim": 2, "csynth": 2, "llm_calls": 0},
            probe=True)))   # probe fired -> auto-derived/fallback path
        # A stray non-arm file the loader must ignore.
        (self.dir / "TABLE.md").write_text("# not a log\n")
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()


class TestPureHelpers(unittest.TestCase):
    def test_category_mapping(self):
        self.assertEqual(at.category_for("matmul_001"), "hand-built")
        self.assertEqual(at.category_for("mac8_001"), "hand-built")
        self.assertEqual(at.category_for("gemm_001"), "PolyBench")
        self.assertEqual(at.category_for("atax_001"), "PolyBench")
        self.assertEqual(at.category_for("bicg_001"), "PolyBench")
        self.assertEqual(at.category_for("nonsense_001"), "other")

    def test_area_and_adp_via_harpo(self):
        cells = at._metric_cells(RECIPE_BEST)
        # area_score / ADP must match harpo.area exactly (area rounded 4 sig).
        self.assertEqual(cells["area_score"],
                         at._fmt(at._round_sig(area_score(RECIPE_BEST), 4)))
        self.assertEqual(cells["ADP"], at._fmt(adp(RECIPE_BEST)))
        # And those are real numbers, not the dash.
        self.assertNotEqual(cells["area_score"], at._DASH)
        self.assertNotEqual(cells["ADP"], at._DASH)

    def test_metric_cells_none(self):
        cells = at._metric_cells(None)
        for key in ("interval_max", "LUT", "area_score", "ADP"):
            self.assertEqual(cells[key], at._DASH)

    def test_accepted_from_improved(self):
        improved_log = _log("matmul_001", baseline=BASELINE, best=RECIPE_BEST,
                            best_id="c", improved=True, tokens=0, spent={})
        kept_log = _log("gemm_001", baseline=BASELINE, best=BASELINE,
                       best_id="cand_0000", improved=False, tokens=0, spent={})
        self.assertEqual(at.accepted_mark(improved_log), "✓")
        self.assertEqual(at.accepted_mark(kept_log), "✗")

    def test_tokens_recipe_zero_llm_nonzero(self):
        recipe_log = _log("matmul_001", baseline=BASELINE, best=RECIPE_BEST,
                         best_id="c", improved=True, tokens=0, spent={})
        llm_log = _log("matmul_001", baseline=BASELINE, best=LLM_BEST,
                      best_id="c", improved=True, tokens=1234, spent={})
        self.assertEqual(at.total_tokens(recipe_log), 0)
        self.assertEqual(at.total_tokens(llm_log), 1234)

    def test_tool_calls_sums_spent(self):
        log = _log("matmul_001", baseline=BASELINE, best=RECIPE_BEST,
                  best_id="c", improved=True, tokens=0,
                  spent={"csim": 4, "csynth": 4, "llm_calls": 6})
        self.assertEqual(at.tool_calls(log), 14)

    def test_method_labels(self):
        recipe_log = _log("matmul_001", baseline=BASELINE, best=RECIPE_BEST,
                         best_id="c", improved=True, tokens=0, spent={})
        self.assertEqual(at.method_label("recipe", recipe_log),
                         "recipe (satisfice_then_area)")
        self.assertEqual(at.method_label("llm", recipe_log), "raw LLM")
        sf_log = _log("matmul_001", baseline=BASELINE, best=RECIPE_BEST,
                     best_id="c", improved=True, tokens=0, spent={},
                     objective="speed_first")
        self.assertEqual(at.method_label("speed_first", sf_log),
                         "recipe (speed_first)")

    def test_target_source_handset_when_no_probe(self):
        # No probe event -> the target was hand-set in the spec.
        log = _log("matmul_001", baseline=BASELINE, best=RECIPE_BEST,
                  best_id="c", improved=True, tokens=0, spent={}, probe=False)
        self.assertEqual(at.target_source(log), "hand-set")

    def test_target_source_auto_derived_vs_fallback(self):
        # Probe target 256 < baseline 512 -> auto-derived (real headroom found).
        auto = _log("gemm_001", baseline=BASELINE, best=RECIPE_BEST,
                   best_id="c", improved=True, tokens=0, spent={},
                   target=256.0, probe=True)
        self.assertEqual(at.target_source(auto), "auto-derived")
        # Probe target == baseline 512 -> fallback (no probe candidate beat it).
        fb = _log("gemm_001", baseline=BASELINE, best=BASELINE,
                 best_id="cand_0000", improved=False, tokens=0, spent={},
                 target=512.0, probe=True)
        self.assertEqual(at.target_source(fb), "fallback")


class TestRowAssembly(unittest.TestCase):
    def test_baseline_dedup_and_ordering(self):
        with _CanonicalDir() as cdir:
            logs = at.load_logs(cdir.dir)
            # The stray TABLE.md must not appear as a "task".
            self.assertEqual(set(logs), {"matmul_001", "gemm_001"})
            self.assertEqual(set(logs["matmul_001"]), {"recipe", "llm"})

            rows = at.build_rows(logs, canonical_dir=None)
            # Exactly ONE baseline row per task (deduped across arms).
            matmul_baselines = [r for r in rows
                                if r["Kernel"] == "matmul_001"
                                and r["Method"] == "baseline"]
            self.assertEqual(len(matmul_baselines), 1)
            gemm_baselines = [r for r in rows
                              if r["Kernel"] == "gemm_001"
                              and r["Method"] == "baseline"]
            self.assertEqual(len(gemm_baselines), 1)

            # Hand-built (matmul) sorts before PolyBench (gemm).
            kernels_in_order = [r["Kernel"] for r in rows]
            self.assertLess(kernels_in_order.index("matmul_001"),
                            kernels_in_order.index("gemm_001"))

            # The baseline row precedes its arm rows for matmul.
            matmul_rows = [i for i, r in enumerate(rows)
                           if r["Kernel"] == "matmul_001"]
            first = matmul_rows[0]
            self.assertEqual(rows[first]["Method"], "baseline")

            # matmul has baseline + recipe + llm = 3 rows; gemm baseline + recipe = 2.
            self.assertEqual(len([r for r in rows if r["Kernel"] == "matmul_001"]), 3)
            self.assertEqual(len([r for r in rows if r["Kernel"] == "gemm_001"]), 2)

    def test_rows_carry_correct_arm_metrics(self):
        with _CanonicalDir() as cdir:
            logs = at.load_logs(cdir.dir)
            rows = at.build_rows(logs, canonical_dir=None)
            llm_row = next(r for r in rows
                           if r["Kernel"] == "matmul_001"
                           and r["Method"] == "raw LLM")
            # LLM best LUT blew up to 9000; tokens nonzero; accepted ✓.
            self.assertEqual(llm_row["LUT"], "9000")
            self.assertEqual(llm_row["Tokens"], "1234")
            self.assertEqual(llm_row["Accepted"], "✓")

            recipe_row = next(r for r in rows
                              if r["Kernel"] == "matmul_001"
                              and r["Method"] == "recipe (satisfice_then_area)")
            self.assertEqual(recipe_row["Tokens"], "0")
            self.assertEqual(recipe_row["LUT"], "900")

    def test_render_markdown_and_csv_well_formed(self):
        with _CanonicalDir() as cdir:
            logs = at.load_logs(cdir.dir)
            rows = at.build_rows(logs, canonical_dir=None)
            md = at.render_markdown(rows)
            self.assertIn("| Kernel | Category |", md)
            # header + separator + one line per row.
            self.assertEqual(len(md.strip().splitlines()), len(rows) + 2)
            csv_text = at.render_csv(rows)
            self.assertTrue(csv_text.startswith("Kernel,Category,"))
            self.assertEqual(len(csv_text.strip().splitlines()), len(rows) + 1)


if __name__ == "__main__":
    unittest.main()
