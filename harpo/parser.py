"""Report Parser: raw tool output -> structured, model-readable result.

The agent is blind without this, so it is deliberately explicit. Status values
form the input to the Diagnosis Engine (next slice).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


def _compile_errors(log: str, limit: int = 20) -> list[str]:
    return [ln.strip() for ln in log.splitlines() if "error:" in ln][:limit]


def _mismatches(stdout: str, limit: int = 20) -> list[str]:
    return [ln.strip() for ln in stdout.splitlines() if "MISMATCH" in ln][:limit]


def parse_csim(raw: dict) -> dict:
    """Normalize a csim run.

    status: tool_unavailable | compile_error | timeout | functional_fail | pass
    pass:   True / False, or None when the tool couldn't run at all.
    """
    parsed = {
        "stage": "csim",
        "backend": raw.get("backend"),
        "compiler": raw.get("compiler"),
        "pass": None,
        "status": None,
        "errors": [],
        "duration_sec": raw.get("duration_sec"),
    }

    if not raw.get("available"):
        parsed["status"] = "tool_unavailable"
        parsed["errors"] = [raw.get("compile_log", "tool unavailable")]
        return parsed

    if raw.get("compile_rc") != 0:
        log = raw.get("compile_log", "") or "compile failed"
        parsed["pass"] = False
        parsed["status"] = "compile_error"
        parsed["errors"] = _compile_errors(log) or [log.splitlines()[0]]
        return parsed

    run_rc = raw.get("run_rc")
    if run_rc == -1:
        parsed["pass"] = False
        parsed["status"] = "timeout"
        parsed["errors"] = [raw.get("run_stderr") or "timeout"]
        return parsed

    if run_rc == 0:
        parsed["pass"] = True
        parsed["status"] = "pass"
        return parsed

    parsed["pass"] = False
    parsed["status"] = "functional_fail"
    parsed["errors"] = _mismatches(raw.get("run_stdout", "")) or \
        [f"testbench returned {run_rc}"]
    return parsed


# ---------------------------------------------------------------------------
# csynth (Vitis HLS)
# ---------------------------------------------------------------------------
def _num(text):
    """'7.300' -> 7.3, '17' -> 17, 'undef'/'?'/'' -> None."""
    if text is None:
        return None
    t = str(text).strip()
    if t in ("", "undef", "?", "-", "N/A", "NA"):
        return None
    try:
        f = float(t)
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


def _txt(node, path):
    if node is None:
        return None
    el = node.find(path)
    return el.text if el is not None else None


def _synth_errors(log: str, limit: int = 20) -> list[str]:
    out = []
    for ln in (log or "").splitlines():
        if "ERROR" in ln or "] ERROR" in ln or ln.strip().startswith("ERROR"):
            out.append(ln.strip())
    return out[:limit]


def _metrics_from_xml(xml_text: str) -> dict:
    """Pull the PPA numbers we score on out of the csynth XML."""
    root = ET.fromstring(xml_text)
    ua = root.find("UserAssignments")
    perf = root.find("PerformanceEstimates")

    m: dict = {
        "part": _txt(ua, "Part"),
        "top": _txt(ua, "TopModelName"),
        "clock_target_ns": _num(_txt(ua, "TargetClockPeriod")),
        "clock_estimated_ns": None,
        "clock_uncertainty_ns": _num(_txt(ua, "ClockUncertainty")),
        "fmax_mhz": None,
        "latency_best": None,
        "latency_worst": None,
        "interval_min": None,
        "interval_max": None,
        "ii": None,
        "depth": None,
        "trip_count": None,
        "lut": None, "ff": None, "dsp": None, "bram_18k": None, "uram": None,
        "avail_lut": None, "avail_ff": None, "avail_dsp": None,
        "avail_bram": None, "avail_uram": None,
        "util_lut": None, "util_ff": None, "util_dsp": None,
        "util_bram": None, "util_uram": None,
    }

    if perf is not None:
        m["clock_estimated_ns"] = _num(
            _txt(perf, "SummaryOfTimingAnalysis/EstimatedClockPeriod"))
        if m["clock_estimated_ns"]:
            m["fmax_mhz"] = round(1000.0 / m["clock_estimated_ns"], 2)
        lat = perf.find("SummaryOfOverallLatency")
        if lat is not None:
            m["latency_best"] = _num(_txt(lat, "Best-caseLatency"))
            m["latency_worst"] = _num(_txt(lat, "Worst-caseLatency"))
            m["interval_min"] = _num(_txt(lat, "Interval-min"))
            m["interval_max"] = _num(_txt(lat, "Interval-max"))
        loops = perf.find("SummaryOfLoopLatency")
        if loops is not None:
            # Worst II / deepest pipeline across all loops.
            for loop in list(loops):
                ii = _num(_txt(loop, "PipelineII"))
                depth = _num(_txt(loop, "PipelineDepth"))
                tc = _num(_txt(loop, "TripCount"))
                if ii is not None:
                    m["ii"] = ii if m["ii"] is None else max(m["ii"], ii)
                if depth is not None:
                    m["depth"] = depth if m["depth"] is None else max(m["depth"], depth)
                if tc is not None:
                    m["trip_count"] = tc

    # Area. The AVAIL_/UTIL_ percentages we score on live in a *nested*
    # <Resources> block in some reports but not others (the per-module
    # <top>_csynth.xml omits it; the overall csynth.xml has it, but Vitis may
    # emit UTIL_* as the non-numeric token "~0" for tiny utilization). So we
    # don't depend on any single block having everything — we merge across all
    # <Resources> blocks for raw counts + AVAIL_/UTIL_, ALSO read the top-level
    # <AvailableResources> block (present in every report, with plain LUT/FF/...
    # tag names), and finally COMPUTE util% from count/avail whenever the report
    # didn't give us a usable UTIL_ value. avail_* is captured for auditability.
    raw_keys = (
        ("lut", "LUT"), ("ff", "FF"), ("dsp", "DSP"),
        ("bram_18k", "BRAM_18K"), ("uram", "URAM"),
    )
    # raw_key -> (avail_key, util_key, AVAIL_tag, UTIL_tag)
    util_map = {
        "lut": ("avail_lut", "util_lut", "AVAIL_LUT", "UTIL_LUT"),
        "ff": ("avail_ff", "util_ff", "AVAIL_FF", "UTIL_FF"),
        "dsp": ("avail_dsp", "util_dsp", "AVAIL_DSP", "UTIL_DSP"),
        "bram_18k": ("avail_bram", "util_bram", "AVAIL_BRAM", "UTIL_BRAM"),
        "uram": ("avail_uram", "util_uram", "AVAIL_URAM", "UTIL_URAM"),
    }

    # 1) Merge every <Resources> block: raw counts + any AVAIL_/UTIL_ fields.
    for res in root.iter("Resources"):
        for raw_k, tag in raw_keys:
            if m[raw_k] is None:
                m[raw_k] = _num(_txt(res, tag))
        for raw_k, (avail_k, util_k, avail_tag, util_tag) in util_map.items():
            if m[avail_k] is None:
                m[avail_k] = _num(_txt(res, avail_tag))
            if m[util_k] is None:
                m[util_k] = _num(_txt(res, util_tag))  # "~0" -> None, recomputed below

    # 2) Top-level <AvailableResources> uses plain tag names (LUT/FF/DSP/...).
    avail = root.find("AreaEstimates/AvailableResources")
    if avail is not None:
        for raw_k, (avail_k, _util_k, _at, _ut) in util_map.items():
            if m[avail_k] is None:
                m[avail_k] = _num(_txt(avail, dict(raw_keys)[raw_k]))

    # 3) Compute util% from count/avail whenever BOTH are known — arithmetic
    #    over the merged counts beats any single reported UTIL_ token. In a
    #    hierarchical overall report there is one <Resources> block per module,
    #    and first-numeric-wins merging can pair the TOP's raw count with a
    #    SUBMODULE's UTIL_ (seen on lns_mac_001: lut=89773 avail=53200 with a
    #    reported util_lut of 6 from a child block; the true top UTIL_LUT was
    #    168 — which silently suppressed the resource-overuse violation). A
    #    reported UTIL_ survives only when util% cannot be computed (missing
    #    count or avail), which also still covers the "~0" token case.
    for raw_k, (avail_k, util_k, _at, _ut) in util_map.items():
        cnt, av = m[raw_k], m[avail_k]
        if cnt is not None and av is not None and av > 0:
            m[util_k] = round(100.0 * cnt / av, 1)
    return m


def parse_csynth(raw: dict) -> dict:
    """Normalize a Vitis HLS csynth run.

    status: tool_unavailable | synthesis_fail | timing_fail | report_missing | pass
    pass:   True when csynth completed and produced a report; False on failure;
            None when the tool could not run.

    timing_fail / resource overuse are surfaced as flags in ``violations`` and
    (for timing) as the status, since they are "synthesized but not good enough"
    rather than hard failures — the optimization loop acts on them.
    """
    parsed = {
        "stage": "csynth",
        "backend": raw.get("backend"),
        "tool": raw.get("tool"),
        "pass": None,
        "status": None,
        "metrics": None,
        "violations": [],
        "errors": [],
        "report_path": raw.get("csynth_report_path"),
        "duration_sec": raw.get("duration_sec"),
    }

    if not raw.get("available"):
        parsed["status"] = "tool_unavailable"
        parsed["errors"] = [raw.get("log", "vitis_hls unavailable")]
        return parsed

    xml_text = raw.get("csynth_xml")
    if not xml_text or raw.get("rc") not in (0, None):
        # Non-zero rc or no report => synthesis did not complete.
        if not xml_text:
            parsed["status"] = "synthesis_fail" if raw.get("rc") else "report_missing"
        else:
            parsed["status"] = "synthesis_fail"
        parsed["pass"] = False
        parsed["errors"] = _synth_errors(raw.get("log", "")) or \
            [f"vitis_hls rc={raw.get('rc')}, no csynth report produced"]
        return parsed

    try:
        m = _metrics_from_xml(xml_text)
    except ET.ParseError as e:
        parsed["status"] = "synthesis_fail"
        parsed["pass"] = False
        parsed["errors"] = [f"could not parse csynth XML: {e}"]
        return parsed

    # If the primary report didn't yield AVAIL/UTIL (e.g. it was a per-module
    # report with no nested block AND no top-level AvailableResources), merge in
    # whatever the secondary report carries. Counts already prefer the primary.
    util_fields = ("util_lut", "util_ff", "util_dsp", "util_bram", "util_uram")
    avail_fields = ("avail_lut", "avail_ff", "avail_dsp", "avail_bram", "avail_uram")
    needs_merge = all(m.get(k) is None for k in util_fields)
    module_xml = raw.get("csynth_xml_module")
    if needs_merge and module_xml:
        try:
            m2 = _metrics_from_xml(module_xml)
        except ET.ParseError:
            m2 = None
        if m2 is not None:
            for k in avail_fields + util_fields:
                if m.get(k) is None and m2.get(k) is not None:
                    m[k] = m2[k]

    parsed["metrics"] = m

    violations = []
    tgt, est = m.get("clock_target_ns"), m.get("clock_estimated_ns")
    if tgt is not None and est is not None and est > tgt:
        violations.append(f"timing: estimated {est}ns > target {tgt}ns")
    for name, cnt_k, avail_k, util_k in (
            ("LUT", "lut", "avail_lut", "util_lut"),
            ("FF", "ff", "avail_ff", "util_ff"),
            ("DSP", "dsp", "avail_dsp", "util_dsp"),
            ("BRAM", "bram_18k", "avail_bram", "util_bram"),
            ("URAM", "uram", "avail_uram", "util_uram")):
        cnt, av, util = m.get(cnt_k), m.get(avail_k), m.get(util_k)
        # Violation strings feed the LLM prompt, and at temperature 0 their
        # exact wording steers the greedy decode — treat any edit here as a
        # behavior change needing re-validation. The utilization form is the
        # wording every recorded run was produced with; the count form fires
        # only for overuse that the 1-decimal util% rounding hides
        # (e.g. 53226/53200 -> util_lut 100.0).
        if util is not None and util > 100:
            violations.append(f"resource: {name} utilization {util}% > 100%")
        elif cnt is not None and av is not None and av > 0 and cnt > av:
            violations.append(f"resource: {name} count {cnt} > available {av} "
                              f"({100.0 * cnt / av:.2f}%)")
    parsed["violations"] = violations

    if any(v.startswith("timing") for v in violations):
        parsed["status"] = "timing_fail"
        parsed["pass"] = False
    elif any(v.startswith("resource") for v in violations):
        parsed["status"] = "resource_overuse"
        parsed["pass"] = False
    else:
        parsed["status"] = "pass"
        parsed["pass"] = True
    return parsed


# ---------------------------------------------------------------------------
# impl (Vivado post-route via Vitis HLS export_design -flow impl)
# ---------------------------------------------------------------------------
def _metrics_from_impl_xml(xml_text: str) -> dict:
    """Pull MEASURED post-route PPA out of export_impl.xml.

    A different, flatter schema than the csynth report: <TimingReport> with
    plain achieved-period/slack/TIMING_MET tags, and <AreaReport> with plain
    LUT/FF/... tags under <Resources> + <AvailableResources>. Resource keys are
    emitted under the SAME names as csynth metrics (lut/avail_lut/util_lut/...)
    so area_score() and the overuse check work unchanged on measured numbers.
    The report carries NO latency/II data — the caller carries those over from
    the candidate's csynth metrics (tagged latency_source="csynth").
    """
    root = ET.fromstring(xml_text)
    timing = root.find("TimingReport")
    res = root.find("AreaReport/Resources")
    avail = root.find("AreaReport/AvailableResources")

    m: dict = {
        "fidelity": "post_route",
        "part": None,
        "clock_target_ns": _num(_txt(timing, "TargetClockPeriod")),
        # Achieved post-route period lands in clock_estimated_ns so the
        # timing check below and downstream fmax/delta tooling read one key
        # for "the period this fidelity reports".
        "clock_estimated_ns": _num(_txt(timing, "AchievedClockPeriod")),
        "fmax_mhz": None,
        "slack_ns": _num(_txt(timing, "SLACK_FINAL")),
        "timing_met": None,
        "lut": None, "ff": None, "dsp": None, "bram_18k": None, "uram": None,
        "avail_lut": None, "avail_ff": None, "avail_dsp": None,
        "avail_bram": None, "avail_uram": None,
        "util_lut": None, "util_ff": None, "util_dsp": None,
        "util_bram": None, "util_uram": None,
    }

    # Part lives in <GeneralInfo><item NAME="Target device" VALUE="..."/>.
    for item in root.iter("item"):
        if item.get("NAME") == "Target device":
            m["part"] = item.get("VALUE")
            break

    met_txt = _txt(timing, "TIMING_MET")
    if met_txt is not None:
        m["timing_met"] = met_txt.strip().upper() == "TRUE"
    if m["clock_estimated_ns"]:
        m["fmax_mhz"] = round(1000.0 / m["clock_estimated_ns"], 2)

    # Impl reports BRAM in RAMB18-equivalents under a plain <BRAM> tag; map it
    # onto the csynth bram_18k key so utilization compares like-for-like.
    tag_map = {
        "lut": "LUT", "ff": "FF", "dsp": "DSP", "bram_18k": "BRAM", "uram": "URAM",
    }
    for raw_k, tag in tag_map.items():
        m[raw_k] = _num(_txt(res, tag))
        m[f"avail_{'bram' if raw_k == 'bram_18k' else raw_k}"] = _num(_txt(avail, tag))
    for raw_k in tag_map:
        avail_k = f"avail_{'bram' if raw_k == 'bram_18k' else raw_k}"
        util_k = f"util_{'bram' if raw_k == 'bram_18k' else raw_k}"
        cnt, av = m[raw_k], m[avail_k]
        if cnt is not None and av is not None and av > 0:
            m[util_k] = round(100.0 * cnt / av, 1)
    return m


def parse_impl(raw: dict) -> dict:
    """Normalize a post-route implementation run (export_design -flow impl).

    status: tool_unavailable | impl_fail | report_missing | timing_fail |
            resource_overuse | pass
    pass:   True when the design routed, met timing, and fits; False otherwise;
            None when the tool could not run.

    Mirrors parse_csynth's contract so the agent/store/event plumbing treats
    the measured rung exactly like the estimate rung.
    """
    parsed = {
        "stage": "impl",
        "backend": raw.get("backend"),
        "tool": raw.get("tool"),
        "pass": None,
        "status": None,
        "metrics": None,
        "violations": [],
        "errors": [],
        "report_path": raw.get("impl_report_path"),
        "duration_sec": raw.get("duration_sec"),
    }

    if not raw.get("available"):
        parsed["status"] = "tool_unavailable"
        parsed["errors"] = [raw.get("log", "vitis_hls unavailable")]
        return parsed

    xml_text = raw.get("impl_xml")
    if not xml_text or raw.get("rc") not in (0, None):
        parsed["status"] = "impl_fail" if raw.get("rc") else "report_missing"
        parsed["pass"] = False
        parsed["errors"] = _synth_errors(raw.get("log", "")) or \
            [f"vitis_hls rc={raw.get('rc')}, no export_impl report produced"]
        return parsed

    try:
        m = _metrics_from_impl_xml(xml_text)
    except ET.ParseError as e:
        parsed["status"] = "impl_fail"
        parsed["pass"] = False
        parsed["errors"] = [f"could not parse export_impl XML: {e}"]
        return parsed

    parsed["metrics"] = m

    violations = []
    tgt, ach = m.get("clock_target_ns"), m.get("clock_estimated_ns")
    if m.get("timing_met") is False or (
            tgt is not None and ach is not None and ach > tgt):
        violations.append(
            f"timing: post-route {ach}ns vs target {tgt}ns (TIMING_MET "
            f"{m.get('timing_met')})")
    for name, cnt_k, avail_k in (
            ("LUT", "lut", "avail_lut"),
            ("FF", "ff", "avail_ff"),
            ("DSP", "dsp", "avail_dsp"),
            ("BRAM", "bram_18k", "avail_bram"),
            ("URAM", "uram", "avail_uram")):
        cnt, av = m.get(cnt_k), m.get(avail_k)
        if cnt is not None and av is not None and av > 0 and cnt > av:
            violations.append(f"resource: {name} count {cnt} > available {av} "
                              f"({100.0 * cnt / av:.2f}%)")
    parsed["violations"] = violations

    if any(v.startswith("timing") for v in violations):
        parsed["status"] = "timing_fail"
        parsed["pass"] = False
    elif any(v.startswith("resource") for v in violations):
        parsed["status"] = "resource_overuse"
        parsed["pass"] = False
    else:
        parsed["status"] = "pass"
        parsed["pass"] = True
    return parsed
