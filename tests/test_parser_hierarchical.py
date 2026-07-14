"""Offline regression tests for csynth parsing of HIERARCHICAL reports.

Pure stdlib `unittest`. No Vitis. The suite's single-module kernels emit one
<Resources> block; a real multi-module design (first seen on lns_mac_001, the
LNS MAC case study) emits one block PER MODULE in the overall csynth.xml.
First-numeric-wins merging could then pair the TOP's raw count with a
SUBMODULE's UTIL_ percentage (lut=89773, avail=53200 → reported util_lut 6),
which silently suppressed the resource-overuse violation. util% must be
COMPUTED from count/avail whenever both are known. Run::

    python3 -m unittest tests.test_parser_hierarchical -v
    python3 tests/test_parser_hierarchical.py
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harpo.parser import parse_csynth

# Mimics the lns_mac_001 overall csynth.xml shape: top block first (Vitis emits
# UTIL_LUT as the "~0"-style token or a stale value), child module blocks after
# it with small counts and their OWN util percentages.
HIERARCHICAL_XML = """\
<profile>
  <UserAssignments>
    <Part>xc7z020-clg400-1</Part>
    <TopModelName>mac_nxn_array</TopModelName>
    <TargetClockPeriod>10.000</TargetClockPeriod>
    <ClockUncertainty>2.70</ClockUncertainty>
  </UserAssignments>
  <PerformanceEstimates>
    <SummaryOfTimingAnalysis>
      <EstimatedClockPeriod>9.500</EstimatedClockPeriod>
    </SummaryOfTimingAnalysis>
    <SummaryOfOverallLatency>
      <Best-caseLatency>3418</Best-caseLatency>
      <Worst-caseLatency>3433</Worst-caseLatency>
      <Interval-min>3419</Interval-min>
      <Interval-max>3434</Interval-max>
    </SummaryOfOverallLatency>
  </PerformanceEstimates>
  <AreaEstimates>
    <Resources>
      <LUT>89773</LUT>
      <FF>43198</FF>
      <DSP>0</DSP>
      <BRAM_18K>4</BRAM_18K>
      <URAM>0</URAM>
      <AVAIL_LUT>53200</AVAIL_LUT>
      <AVAIL_FF>106400</AVAIL_FF>
      <AVAIL_DSP>220</AVAIL_DSP>
      <AVAIL_BRAM>280</AVAIL_BRAM>
      <AVAIL_URAM>0</AVAIL_URAM>
      <UTIL_LUT>~0</UTIL_LUT>
      <UTIL_FF>~0</UTIL_FF>
    </Resources>
    <Resources>
      <LUT>3709</LUT>
      <FF>1200</FF>
      <UTIL_LUT>6</UTIL_LUT>
      <UTIL_FF>1</UTIL_FF>
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


def _raw(xml: str) -> dict:
    return {
        "stage": "csynth", "backend": "vitis_hls", "available": True,
        "tool": "vitis_hls", "rc": 0, "log": "",
        "csynth_xml": xml, "csynth_xml_module": None,
        "csynth_report_path": "x.xml", "duration_sec": 0.0,
    }


class TestHierarchicalUtilPairing(unittest.TestCase):
    def setUp(self):
        self.parsed = parse_csynth(_raw(HIERARCHICAL_XML))
        self.m = self.parsed["metrics"]

    def test_raw_counts_come_from_top_block(self):
        self.assertEqual(self.m["lut"], 89773)
        self.assertEqual(self.m["avail_lut"], 53200)

    def test_util_computed_not_taken_from_child_block(self):
        """REGRESSION: reported util_lut=6 (child module) must lose to the
        computed 100*89773/53200 = 168.7."""
        self.assertAlmostEqual(self.m["util_lut"], 168.7, places=1)
        self.assertAlmostEqual(self.m["util_ff"], round(100.0 * 43198 / 106400, 1))

    def test_overuse_violation_raised_and_status_set(self):
        self.assertTrue(any(v.startswith("resource: LUT") for v in
                            self.parsed["violations"]))
        # Timing is fine in this fixture, so overuse drives the status.
        self.assertEqual(self.parsed["status"], "resource_overuse")
        self.assertIs(self.parsed["pass"], False)

    def test_uram_unavailable_stays_none(self):
        # avail_uram == 0 -> util cannot be computed and must stay None
        # (resource doesn't exist on the part; not a violation).
        self.assertIsNone(self.m["util_uram"])


if __name__ == "__main__":
    unittest.main()
