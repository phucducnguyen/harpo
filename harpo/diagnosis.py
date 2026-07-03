"""Diagnosis Engine: parser status -> a reasoned Diagnosis for the loop.

Consumes the `parsed` dict from parser.py and emits a Diagnosis (models.py)
the patcher / control loop acts on. Deliberately rule-based and deterministic —
no model call here; the agent reasons about the result, not this mapping.
"""

from __future__ import annotations

from .models import Diagnosis, DIAGNOSIS_CLASSES, ACTIONS

# parser status -> (klass, recommended_action, confidence). Single source of
# truth for the mapping; the "anything else / missing" case is the fallback.
_STATUS_MAP = {
    "pass":             ("PASS",                 "none",                      1.0),
    "compile_error":    ("COMPILE_ERROR",        "minimal_compile_fix",       0.9),
    "functional_fail":  ("CSIM_FUNCTIONAL_FAIL", "minimal_functional_patch",  0.85),
    "timeout":          ("TIMEOUT_OR_DEADLOCK",  "fix_loop_or_protocol",      0.7),
    "tool_unavailable": ("TOOL_UNAVAILABLE",     "none",                      1.0),
}
_FALLBACK = ("UNKNOWN", "rollback_or_escalate", 0.3)

# Klasses that are not actually failures — we don't escalate on a repeat.
_NON_FAILURE = ("PASS", "TOOL_UNAVAILABLE")

# One-line, human-readable summary per status for the evidence trail.
_SUMMARIES = {
    "pass":             "csim passed",
    "compile_error":    "compilation failed",
    "functional_fail":  "csim ran but testbench reported a mismatch",
    "timeout":          "run timed out (possible loop/protocol deadlock)",
    "tool_unavailable": "tool unavailable — could not run",
}

_MAX_EVIDENCE = 5


# csynth status -> (klass, recommended_action, confidence). PPA violations and
# a clean-but-improvable pass both route to the optimizer; a synthesizability
# failure routes back to a code repair.
_CSYNTH_STATUS_MAP = {
    "pass":             ("PASS",              "optimize_ppa",          0.9),
    "timing_fail":      ("TIMING_FAIL",       "optimize_ppa",          0.9),
    "resource_overuse": ("RESOURCE_OVERUSE",  "optimize_ppa",          0.9),
    "synthesis_fail":   ("SYNTHESIS_FAIL",    "fix_loop_or_protocol",  0.8),
    "report_missing":   ("SYNTHESIS_FAIL",    "fix_loop_or_protocol",  0.5),
    "tool_unavailable": ("TOOL_UNAVAILABLE",  "none",                  1.0),
}


def _metrics_evidence(metrics: dict) -> list[str]:
    m = metrics or {}
    if not m:
        return []
    return [
        (f"II={m.get('ii')} depth={m.get('depth')} "
         f"latency_worst={m.get('latency_worst')} "
         f"clk target={m.get('clock_target_ns')}ns est={m.get('clock_estimated_ns')}ns "
         f"fmax={m.get('fmax_mhz')}MHz"),
        (f"LUT={m.get('lut')}({m.get('util_lut')}%) "
         f"FF={m.get('ff')}({m.get('util_ff')}%) "
         f"DSP={m.get('dsp')}({m.get('util_dsp')}%) "
         f"BRAM={m.get('bram_18k')}({m.get('util_bram')}%)"),
    ]


def diagnose_csynth(parsed: dict, history: list[str] | None = None) -> Diagnosis:
    """Map a parsed csynth run into a Diagnosis for the optimization loop.

    A clean pass still yields recommended_action ``optimize_ppa`` (there may be
    headroom on II/latency/area); violations route to the optimizer too; a
    synthesizability failure routes to a code repair. Evidence carries the PPA
    metrics + violations so the patcher can target the right knob.
    """
    history = history or []
    status = parsed.get("status")
    klass, action, confidence = _CSYNTH_STATUS_MAP.get(status, _FALLBACK)

    evidence = _metrics_evidence(parsed.get("metrics"))
    evidence.extend(parsed.get("violations") or [])
    evidence.extend(str(e) for e in (parsed.get("errors") or [])[:_MAX_EVIDENCE])
    if not evidence:
        evidence = [f"csynth status: {status!r}"]

    repeated = klass in history and klass not in _NON_FAILURE

    assert klass in DIAGNOSIS_CLASSES, f"bad klass: {klass}"
    assert action in ACTIONS, f"bad action: {action}"
    return Diagnosis(
        klass=klass,
        confidence=confidence,
        evidence=evidence,
        recommended_action=action,
        repeated=repeated,
    )


def diagnose(parsed: dict, history: list[str] | None = None) -> Diagnosis:
    """Map a parsed run into a Diagnosis.

    history is prior Diagnosis.klass strings (most recent last). If the klass we
    return already appears there we mark repeated=True, and for a *failure* klass
    we escalate the action to rollback_or_escalate — re-trying the same failing
    fix is wasted budget.
    """
    history = history or []
    status = parsed.get("status")
    klass, action, confidence = _STATUS_MAP.get(status, _FALLBACK)

    # Evidence: first few parser errors, capped, plus a one-line status summary.
    errors = parsed.get("errors") or []
    summary = _SUMMARIES.get(status, f"unrecognized status: {status!r}")
    evidence = [str(e) for e in errors[:_MAX_EVIDENCE]]
    evidence.append(summary)

    # Repeat handling: same klass seen before -> escalate failures.
    repeated = klass in history
    if repeated and klass not in _NON_FAILURE:
        action = "rollback_or_escalate"

    # Defensive: never emit a value outside the declared contracts.
    assert klass in DIAGNOSIS_CLASSES, f"bad klass: {klass}"
    assert action in ACTIONS, f"bad action: {action}"

    return Diagnosis(
        klass=klass,
        confidence=confidence,
        evidence=evidence,
        recommended_action=action,
        repeated=repeated,
    )
