"""Safety-invariant credibility test for the HARPO optimize loop.

Proves the hard invariant of ``run_optimize``: a patch that would IMPROVE
throughput but BREAKS correctness is rejected, and the correct baseline is
preserved. This is the paper's safety claim, exercised end-to-end with a REAL
g++ csim — no Vitis required.

How it runs hermetically (no Vitis):
  * csim runs FOR REAL on the gpp backend (g++ compiles + runs the testbench),
    so the broken patch's wrong output is detected by actually executing it.
  * csynth needs Vitis, which is absent in test/CI. We monkeypatch
    ``harpo.agent.run_stage`` so ONLY the "csynth" stage returns a canned
    raw dict (a minimal but valid Vitis csynth XML); the REAL ``parse_csynth``
    then turns it into a deterministic clean pass with fixed metrics. The
    "csim" stage is delegated to the real ``run_stage`` so g++ runs unchanged.
  * ``harpo.store.REPO_ROOT`` is repointed at a tempdir so the run's
    ``runs/<task>/`` evidence lands there and is cleaned up.

Pure stdlib ``unittest``::

    python3 -m unittest tests.test_optimize_safety -v
    python3 tests/test_optimize_safety.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Allow `python3 tests/test_optimize_safety.py` (repo root not on sys.path).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harpo import agent, store
from harpo.agent import run_optimize
from harpo.patch_engine import MockProvider
from harpo.runner import run_stage as real_run_stage
from harpo.task import load_task

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_DIR = REPO_ROOT / "tasks" / "trap_breakscsim_001"


# A minimal but VALID Vitis HLS csynth report. The real parse_csynth /
# _metrics_from_xml read this and must yield a clean PASS (estimated clock <=
# target so no timing violation; counts well under available so no resource
# violation). Metrics are fixed for determinism: II=4, worst latency=1026,
# LUT=300 of 53200 available (~0.6%).
CANNED_CSYNTH_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<profile>
  <UserAssignments>
    <Part>xc7z020clg400-1</Part>
    <TopModelName>wsum</TopModelName>
    <TargetClockPeriod>10.00</TargetClockPeriod>
    <ClockUncertainty>1.25</ClockUncertainty>
  </UserAssignments>
  <PerformanceEstimates>
    <SummaryOfTimingAnalysis>
      <EstimatedClockPeriod>8.500</EstimatedClockPeriod>
    </SummaryOfTimingAnalysis>
    <SummaryOfOverallLatency>
      <Best-caseLatency>1026</Best-caseLatency>
      <Worst-caseLatency>1026</Worst-caseLatency>
      <Interval-min>1027</Interval-min>
      <Interval-max>1027</Interval-max>
    </SummaryOfOverallLatency>
    <SummaryOfLoopLatency>
      <wsum_label0>
        <PipelineII>4</PipelineII>
        <PipelineDepth>8</PipelineDepth>
        <TripCount>128</TripCount>
      </wsum_label0>
    </SummaryOfLoopLatency>
  </PerformanceEstimates>
  <AreaEstimates>
    <Resources>
      <LUT>300</LUT>
      <FF>200</FF>
      <DSP>0</DSP>
      <BRAM_18K>0</BRAM_18K>
      <URAM>0</URAM>
    </Resources>
    <AvailableResources>
      <LUT>53200</LUT>
      <FF>106400</FF>
      <DSP>220</DSP>
      <BRAM_18K>280</BRAM_18K>
      <URAM>0</URAM>
    </AvailableResources>
  </AreaEstimates>
</profile>
"""


def _canned_csynth_raw() -> dict:
    """Shape mirrors run_csynth_vitis's return so parse_csynth runs for real."""
    return {
        "stage": "csynth",
        "backend": "vitis_hls",
        "available": True,
        "tool": "canned",
        "rc": 0,
        "log": "",
        "csynth_xml": CANNED_CSYNTH_XML,
        "csynth_xml_module": None,
        "csynth_rpt": None,
        "csynth_report_path": "canned://wsum_csynth.xml",
        "csim_log": None,
        "duration_sec": 0.0,
    }


class OptimizeSafetyInvariantTest(unittest.TestCase):
    """A correctness-breaking 'optimization' must be discarded, baseline kept."""

    def setUp(self):
        # Isolate all run/evidence writes into a tempdir so the test is
        # self-contained and leaves no runs/ artifacts behind.
        self._tmp = tempfile.mkdtemp(prefix="harpo_safety_")
        self._orig_repo_root = store.REPO_ROOT
        store.REPO_ROOT = Path(self._tmp)
        self.addCleanup(self._restore_repo_root)
        self.addCleanup(shutil.rmtree, self._tmp, True)

        # Monkeypatch the stage dispatcher seen by the agent: csynth is canned
        # (no Vitis), csim is delegated to the real g++ backend.
        self._orig_run_stage = agent.run_stage

        def fake_run_stage(task, stage, out_dir, backend="gpp"):
            if stage == "csynth":
                return _canned_csynth_raw()
            return real_run_stage(task, stage, out_dir, backend=backend)

        agent.run_stage = fake_run_stage
        self.addCleanup(self._restore_run_stage)

        # Load the trap task exactly like the CLI does.
        self.task = load_task(TASK_DIR)
        # The trap edits, loaded the same way cli._build_providers loads them.
        self.trap_edits = [
            tuple(e) for e in json.loads((TASK_DIR / "mock_patch.json").read_text())
        ]

    def _restore_repo_root(self):
        store.REPO_ROOT = self._orig_repo_root

    def _restore_run_stage(self):
        agent.run_stage = self._orig_run_stage

    def test_breaking_optimization_is_rejected(self):
        # Skip cleanly rather than fail spuriously if no C++ compiler is present
        # (csim must actually run for this test to mean anything).
        if shutil.which(os.environ.get("CXX") or "") is None and not any(
            shutil.which(c) for c in ("g++", "clang++", "c++")
        ):
            self.skipTest("no C++ compiler available; gpp csim cannot run")

        result = run_optimize(
            self.task,
            providers=[MockProvider(self.trap_edits)],
            csim_backend="gpp",
            synth_backend="vitis_hls",
            max_steps=4,
            patience=2,
        )

        # (a) the run completed and produced a structured result.
        self.assertEqual(result["task_id"], "trap_breakscsim_001")
        self.assertEqual(result["phase"], "optimize")
        candidates = result["candidates"]
        self.assertGreaterEqual(
            len(candidates), 2,
            "expected a baseline + at least one (broken) child candidate")

        baseline_id = candidates[0]["candidate_id"]

        # The baseline itself must be correct (csim pass) — otherwise the test
        # would be vacuous (optimize bails before ever applying the trap).
        self.assertTrue(
            candidates[0]["csim_pass"],
            "baseline must pass csim for the trap to be exercised")

        # (b) the broken child was created AND discarded as a regression.
        events = result["events"]
        regressions = [e for e in events if e.get("event") == "regression"]
        self.assertTrue(
            regressions,
            "expected a 'regression' event for the correctness-breaking child")

        broken_children = [
            c for c in candidates
            if c["candidate_id"] != baseline_id and not c["csim_pass"]
        ]
        self.assertTrue(
            broken_children,
            "expected at least one child whose csim_pass is False")

        # The broken child must NOT be the winner.
        self.assertNotIn(
            result["best_candidate"],
            [c["candidate_id"] for c in broken_children],
            "a correctness-breaking child must never win")

        # (c) the winning/best candidate IS the baseline.
        self.assertEqual(
            result["best_candidate"], baseline_id,
            "the correct baseline must be preserved as the best candidate")

        # (d) no improvement was accepted.
        self.assertFalse(
            result["improved"],
            "a correctness-breaking 'optimization' must not count as improved")

        # And, for good measure: no 'accept' event ever fired.
        self.assertFalse(
            [e for e in events if e.get("event") == "accept"],
            "no optimization should have been accepted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
