"""Multi-fidelity credibility tests for the post-route impl-verify rung.

The motivating measurement (LNS MAC, 2026-07-15): csynth estimated 21,013 LUTs
where post-route measured 8,596 — ~2.4x pessimistic, with no guarantee of
direction. So an optimize loop that ranks winners on csynth estimates inherits
the estimator's error. The impl-verify rung re-measures the top-K candidates
(+ the baseline) with a real Vivado implementation and picks the winner from
MEASURED numbers, recording the estimate winner alongside.

What is proven here, hermetically (no Vitis/Vivado, no compiler needed):
  * parse_impl normalizes export_impl.xml (a different, flatter schema than
    csynth's) into the SAME metric keys, so area_score/overuse checks reuse.
  * _gen_impl_tcl skips csim/cosim, runs export_design -flow impl, and still
    excludes host-csim-only include_dirs.
  * End-to-end: when measured PPA REVERSES the estimate ranking, the measured
    winner is selected (winner_fidelity="post_route"), the estimate winner is
    recorded for comparison, and 'improved' is computed at measured fidelity.
  * Fail-open: an unavailable impl backend falls back to the estimate winner.

How it runs hermetically: ``harpo.agent.run_stage`` is monkeypatched so ALL
stages return canned raw dicts shaped exactly like the real backends' returns
(the real parse_csim/parse_csynth/parse_impl then run unmodified), and
``harpo.store.REPO_ROOT`` is repointed at a tempdir. Same conventions as
tests/test_optimize_safety.py.

Pure stdlib ``unittest``::

    python3 -m unittest tests.test_impl_verify -v
    python3 tests/test_impl_verify.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harpo import agent, store
from harpo.agent import run_optimize
from harpo.parser import parse_impl
from harpo.patch_engine import MockProvider
from harpo.runner import _gen_impl_tcl
from harpo.task import TaskContext, load_task


# ---------------------------------------------------------------------------
# Canned reports (parameterized so tests can flip rankings)
# ---------------------------------------------------------------------------
def _csynth_xml(lut: int, interval: int = 100) -> str:
    """Minimal valid csynth XML; clean pass with a chosen LUT estimate."""
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<profile>
  <UserAssignments>
    <Part>xc7z020clg400-1</Part>
    <TopModelName>k</TopModelName>
    <TargetClockPeriod>10.00</TargetClockPeriod>
    <ClockUncertainty>1.25</ClockUncertainty>
  </UserAssignments>
  <PerformanceEstimates>
    <SummaryOfTimingAnalysis>
      <EstimatedClockPeriod>8.500</EstimatedClockPeriod>
    </SummaryOfTimingAnalysis>
    <SummaryOfOverallLatency>
      <Best-caseLatency>{interval - 1}</Best-caseLatency>
      <Worst-caseLatency>{interval - 1}</Worst-caseLatency>
      <Interval-min>{interval}</Interval-min>
      <Interval-max>{interval}</Interval-max>
    </SummaryOfOverallLatency>
  </PerformanceEstimates>
  <AreaEstimates>
    <Resources>
      <LUT>{lut}</LUT>
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


def _impl_xml(lut: int, achieved_ns: float = 9.362,
              timing_met: str = "TRUE", avail_lut: int = 53200) -> str:
    """Minimal valid export_impl.xml; mirrors the real report's flat schema."""
    return f"""\
<profile>
  <RunData>
    <RUN_TYPE>impl</RUN_TYPE>
  </RunData>
  <TimingReport>
    <TargetClockPeriod>10.000</TargetClockPeriod>
    <AchievedClockPeriod>{achieved_ns}</AchievedClockPeriod>
    <SLACK_FINAL>0.638</SLACK_FINAL>
    <TIMING_MET>{timing_met}</TIMING_MET>
  </TimingReport>
  <AreaReport>
    <Resources>
      <BRAM>2</BRAM>
      <DSP>0</DSP>
      <FF>8675</FF>
      <LUT>{lut}</LUT>
      <SLICE>3275</SLICE>
      <URAM>0</URAM>
    </Resources>
    <AvailableResources>
      <BRAM>280</BRAM>
      <DSP>220</DSP>
      <FF>106400</FF>
      <LUT>{avail_lut}</LUT>
      <URAM>0</URAM>
    </AvailableResources>
  </AreaReport>
  <GeneralInfo NAME="General Information">
    <item NAME="Target device" VALUE="xc7z020-clg400-1"/>
  </GeneralInfo>
</profile>
"""


def _impl_raw(xml_text: str | None, available: bool = True, rc: int = 0) -> dict:
    """Shape mirrors run_impl_vitis's return so parse_impl runs for real."""
    return {
        "stage": "impl",
        "backend": "vitis_hls",
        "available": available,
        "tool": "canned" if available else None,
        "rc": rc if available else None,
        "log": "" if available else "vitis_hls not found",
        "impl_xml": xml_text,
        "impl_report_path": "canned://export_impl.xml" if xml_text else None,
        "duration_sec": 0.0,
    }


def _csynth_raw(xml_text: str) -> dict:
    return {
        "stage": "csynth", "backend": "vitis_hls", "available": True,
        "tool": "canned", "rc": 0, "log": "",
        "csynth_xml": xml_text, "csynth_xml_module": None, "csynth_rpt": None,
        "csynth_report_path": "canned://csynth.xml", "csim_log": None,
        "duration_sec": 0.0,
    }


def _csim_raw_pass() -> dict:
    return {
        "stage": "csim", "backend": "gpp", "available": True,
        "compiler": "canned", "compile_rc": 0, "compile_log": "",
        "run_rc": 0, "run_stdout": "", "run_stderr": "", "duration_sec": 0.0,
    }


# ---------------------------------------------------------------------------
# parse_impl unit tests (pattern A: canned raw dict, real parser)
# ---------------------------------------------------------------------------
class ParseImplTest(unittest.TestCase):

    def test_clean_pass_and_metric_key_parity(self):
        parsed = parse_impl(_impl_raw(_impl_xml(lut=8596)))
        self.assertEqual(parsed["status"], "pass")
        self.assertTrue(parsed["pass"])
        m = parsed["metrics"]
        self.assertEqual(m["fidelity"], "post_route")
        # Same key names as csynth metrics so area_score()/overuse reuse.
        self.assertEqual(m["lut"], 8596)
        self.assertEqual(m["avail_lut"], 53200)
        self.assertEqual(m["util_lut"], 16.2)
        # <BRAM> (RAMB18 units) maps onto the csynth bram_18k key.
        self.assertEqual(m["bram_18k"], 2)
        self.assertEqual(m["avail_bram"], 280)
        self.assertEqual(m["clock_target_ns"], 10.0)
        self.assertEqual(m["clock_estimated_ns"], 9.362)
        self.assertTrue(m["timing_met"])
        self.assertEqual(m["part"], "xc7z020-clg400-1")

    def test_timing_fail(self):
        parsed = parse_impl(_impl_raw(
            _impl_xml(lut=100, achieved_ns=11.2, timing_met="FALSE")))
        self.assertEqual(parsed["status"], "timing_fail")
        self.assertFalse(parsed["pass"])
        self.assertTrue(any(v.startswith("timing") for v in parsed["violations"]))

    def test_resource_overuse(self):
        parsed = parse_impl(_impl_raw(_impl_xml(lut=60000, avail_lut=53200)))
        self.assertEqual(parsed["status"], "resource_overuse")
        self.assertFalse(parsed["pass"])
        self.assertTrue(any("LUT" in v for v in parsed["violations"]))

    def test_tool_unavailable(self):
        parsed = parse_impl(_impl_raw(None, available=False))
        self.assertEqual(parsed["status"], "tool_unavailable")
        self.assertIsNone(parsed["pass"])

    def test_report_missing(self):
        parsed = parse_impl(_impl_raw(None, available=True, rc=0))
        self.assertEqual(parsed["status"], "report_missing")
        self.assertFalse(parsed["pass"])

    def test_impl_fail_on_nonzero_rc(self):
        parsed = parse_impl(_impl_raw(None, available=True, rc=1))
        self.assertEqual(parsed["status"], "impl_fail")
        self.assertFalse(parsed["pass"])


# ---------------------------------------------------------------------------
# Tcl generation (pure string function, no subprocess)
# ---------------------------------------------------------------------------
class GenImplTclTest(unittest.TestCase):

    def _task(self, tmp: Path) -> TaskContext:
        return TaskContext(
            task_id="t", task_dir=tmp, top_function="k", language="cpp",
            src_files=[tmp / "src" / "k.cpp"], tb_files=[tmp / "tb" / "tb.cpp"],
            src_dir=tmp / "src", tb_dir=tmp / "tb",
            clock_period_ns=10.0, fpga_part="xc7z020clg400-1",
            policy={}, budget={},
            include_dirs=[tmp / "vendored_headers"],
        )

    def test_impl_tcl_shape(self):
        tmp = Path(tempfile.mkdtemp(prefix="harpo_impltcl_"))
        self.addCleanup(shutil.rmtree, str(tmp), True)
        tcl = _gen_impl_tcl(self._task(tmp), "impl_proj")

        self.assertIn("export_design -flow impl -rtl verilog", tcl)
        self.assertIn("csynth_design", tcl)
        self.assertIn("set_part {xc7z020clg400-1}", tcl)
        self.assertIn("create_clock -period 10.0", tcl)
        self.assertIn("set_top k", tcl)
        # Correctness is gated upstream: no csim, no cosim in the impl run.
        self.assertNotIn("csim_design", tcl)
        self.assertNotIn("cosim", tcl)
        # Host-csim-only vendored headers must never reach the real tool.
        self.assertNotIn("vendored_headers", tcl)


# ---------------------------------------------------------------------------
# End-to-end optimize + impl-verify (pattern B: monkeypatched dispatcher)
# ---------------------------------------------------------------------------
class ImplVerifyLoopTest(unittest.TestCase):
    """Measured PPA reverses the estimate ranking -> measured winner selected."""

    # Estimates say the child (cand_0001, LUT 500) beats the baseline
    # (cand_0000, LUT 1000). Measurement says the opposite: baseline routes at
    # LUT 300, child at LUT 900. The estimate winner and measured winner MUST
    # differ — that divergence is the experiment the rung exists to record.
    CSYNTH_LUT = {"cand_0000": 1000, "cand_0001": 500}
    IMPL_LUT = {"cand_0000": 300, "cand_0001": 900}

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="harpo_implverify_")
        self.addCleanup(shutil.rmtree, self._tmp, True)
        self._orig_repo_root = store.REPO_ROOT
        store.REPO_ROOT = Path(self._tmp)
        self.addCleanup(self._restore_repo_root)

        self.task_dir = Path(self._tmp) / "task"
        self._write_task(self.task_dir)
        self.task = load_task(self.task_dir)

        self._orig_run_stage = agent.run_stage
        self.addCleanup(self._restore_run_stage)

    def _restore_repo_root(self):
        store.REPO_ROOT = self._orig_repo_root

    def _restore_run_stage(self):
        agent.run_stage = self._orig_run_stage

    def _write_task(self, d: Path):
        (d / "src").mkdir(parents=True)
        (d / "tb").mkdir(parents=True)
        (d / "src" / "k.cpp").write_text(
            "void k(int *a) { *a = 1; } // V1\n")
        (d / "tb" / "tb.cpp").write_text("int main() { return 0; }\n")
        (d / "spec.json").write_text(json.dumps({
            "task_id": "impl_verify_e2e",
            "top_function": "k",
            "entry_files": ["src/k.cpp"],
            "testbench_files": ["tb/tb.cpp"],
            "objective": "area_first",
        }))
        (d / "constraints.json").write_text(json.dumps({
            "target": {"clock_period_ns": 10.0,
                       "fpga_part": "xc7z020clg400-1"},
        }))
        (d / "budget.json").write_text("{}")

    def _fake_run_stage(self, impl_available: bool = True):
        csynth_lut, impl_lut = self.CSYNTH_LUT, self.IMPL_LUT

        def fake(task, stage, out_dir, backend="gpp"):
            cand_id = Path(out_dir).name
            if stage == "csim":
                return _csim_raw_pass()
            if stage == "csynth":
                return _csynth_raw(_csynth_xml(lut=csynth_lut[cand_id]))
            if stage == "impl":
                if not impl_available:
                    return _impl_raw(None, available=False)
                return _impl_raw(_impl_xml(lut=impl_lut[cand_id]))
            raise AssertionError(f"unexpected stage {stage}")

        return fake

    def _providers(self):
        # One area-reducing (by estimate) edit; whole-file, contract-clean.
        return [MockProvider([("k.cpp", "V1", "V2")])]

    def test_measured_ranking_overrides_estimates(self):
        agent.run_stage = self._fake_run_stage(impl_available=True)

        result = run_optimize(
            self.task, self._providers(),
            csim_backend="gpp", synth_backend="vitis_hls",
            max_steps=1, patience=1, impl_verify=1,
        )

        # The child was accepted on estimates (500 < 1000 LUT)...
        self.assertEqual(result["best_candidate_estimate"], "cand_0001")
        # ...but measurement reversed the ranking: the baseline wins.
        self.assertEqual(result["winner_fidelity"], "post_route")
        self.assertEqual(result["best_candidate"], "cand_0000")
        self.assertFalse(
            result["improved"],
            "winner == baseline at measured fidelity must not count as improved")

        # Both pool members (top-1 + baseline) were measured, on budget.
        impl_events = [e for e in result["events"]
                       if e.get("event") == "impl_verify"]
        self.assertEqual(len(impl_events), 2)
        self.assertEqual(result["budget"]["spent"].get("impl"), 2)

        # Measured metrics are attached WITHOUT overwriting the estimates,
        # and carry the csynth latency fields (impl reports have none).
        by_id = {c["candidate_id"]: c for c in result["candidates"]}
        base = by_id["cand_0000"]
        self.assertEqual(base["csynth_metrics"]["lut"], 1000)
        self.assertEqual(base["impl_metrics"]["lut"], 300)
        self.assertEqual(base["impl_metrics"]["latency_source"], "csynth")
        self.assertEqual(base["impl_metrics"]["interval_max"],
                         base["csynth_metrics"]["interval_max"])
        self.assertEqual(result["best_impl_metrics"]["lut"], 300)

        # Evidence trail: stage-prefixed impl files exist for both candidates.
        for cand_id in ("cand_0000", "cand_0001"):
            d = store.candidate_dir("impl_verify_e2e", cand_id)
            self.assertTrue((d / "impl_raw.json").exists())
            self.assertTrue((d / "impl_parsed.json").exists())

    def test_fail_open_when_impl_unavailable(self):
        agent.run_stage = self._fake_run_stage(impl_available=False)

        result = run_optimize(
            self.task, self._providers(),
            csim_backend="gpp", synth_backend="vitis_hls",
            max_steps=1, patience=1, impl_verify=1,
        )

        # No measurement possible -> today's estimate-based behavior, intact.
        self.assertEqual(result["winner_fidelity"], "csynth_estimate")
        self.assertEqual(result["best_candidate"], "cand_0001")
        self.assertEqual(result["best_candidate_estimate"], "cand_0001")
        self.assertTrue(result["improved"])
        self.assertIsNone(result["best_impl_metrics"])

    def test_rung_off_by_default(self):
        agent.run_stage = self._fake_run_stage(impl_available=True)

        result = run_optimize(
            self.task, self._providers(),
            csim_backend="gpp", synth_backend="vitis_hls",
            max_steps=1, patience=1,   # no impl_verify, task sets no top_k
        )

        self.assertEqual(result["winner_fidelity"], "csynth_estimate")
        self.assertNotIn("impl", result["budget"]["spent"])
        self.assertFalse([e for e in result["events"]
                          if e.get("event") == "impl_verify"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
