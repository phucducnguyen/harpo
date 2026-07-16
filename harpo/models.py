"""Shared data models for the HARPO repair/optimize loop.

These are the contracts between components (diagnosis, patch_engine, candidate,
budget, agent). Keep them stable — modules import FROM here, never redefine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------
# Failure classes the agent reasons about. csim-era ones are live now; the
# csynth-era ones are reserved for when the Vitis backend lands (Gate 0b).
DIAGNOSIS_CLASSES = (
    "PASS",
    "COMPILE_ERROR",
    "CSIM_FUNCTIONAL_FAIL",
    "TIMEOUT_OR_DEADLOCK",
    "TOOL_UNAVAILABLE",
    "UNKNOWN",
    # csynth-era (live with the vitis_hls backend, Gate 0b):
    "SYNTHESIS_FAIL",      # csynth errored / non-synthesizable construct
    "TIMING_FAIL",         # estimated clock exceeds the target period
    "II_TOO_HIGH",         # loop initiation interval worse than target
    "RESOURCE_OVERUSE",    # a resource exceeds what the part provides
)

# Recommended next action for the patcher / control loop.
ACTIONS = (
    "none",
    "minimal_compile_fix",
    "minimal_functional_patch",
    "fix_loop_or_protocol",
    "optimize_ppa",
    "rollback_or_escalate",
)


@dataclass
class Diagnosis:
    klass: str                 # one of DIAGNOSIS_CLASSES
    confidence: float          # 0.0 .. 1.0
    evidence: list[str]        # short human-readable signals from the parse
    recommended_action: str    # one of ACTIONS
    repeated: bool = False      # same klass already seen in history this run

    def to_dict(self) -> dict:
        return {
            "klass": self.klass,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "recommended_action": self.recommended_action,
            "repeated": self.repeated,
        }


# ---------------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------------
@dataclass
class PatchProposal:
    """One minimal patch from a PatchProvider. Prefer whole_file for small
    kernels (robust); patch_unified_diff is the optional cheaper representation."""
    diagnosis: str                       # the Diagnosis.klass this addresses
    edit_plan: str                       # one-line intent
    target_file: str                     # path RELATIVE to the candidate src root
    patch_unified_diff: str | None = None
    whole_file: str | None = None        # full replacement contents of target_file
    expected_effect: str = ""
    risk_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "diagnosis": self.diagnosis,
            "edit_plan": self.edit_plan,
            "target_file": self.target_file,
            "has_diff": self.patch_unified_diff is not None,
            "has_whole_file": self.whole_file is not None,
            "expected_effect": self.expected_effect,
            "risk_tags": self.risk_tags,
        }


@dataclass
class ApplyResult:
    ok: bool
    method: str                          # "whole_file" | "unified_diff" | "none"
    file: str | None = None              # relative path actually written
    reasons: list[str] = field(default_factory=list)  # rejection reasons if !ok


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    """A versioned attempt. Each owns an isolated src/ copy under workdir so
    patches never mutate the original task."""
    candidate_id: str
    workdir: Path                        # runs/<task_id>/<candidate_id>/
    src_dir: Path                        # workdir/src  (editable copy)
    parent_id: str | None = None
    csim_status: str | None = None       # parser status string
    csim_pass: bool = False
    csynth_pass: bool = False
    csynth_status: str | None = None     # csynth parser status string
    csynth_metrics: dict | None = None   # PPA: ii/depth/latency/lut/ff/dsp/bram/...
    impl_pass: bool = False
    impl_status: str | None = None       # impl (post-route) parser status string
    impl_metrics: dict | None = None     # MEASURED post-route PPA; kept separate from
    #                                      csynth_metrics so the estimate-vs-measured
    #                                      trail survives as evidence
    objective: str = "satisfice_then_area"  # enum: speed_first | area_first | adp | satisfice_then_area | pareto_report
    throughput_target: float | None = None  # interval_max ceiling for satisfice_then_area; None = no explicit target
    budget_spent: dict = field(default_factory=dict)
    diagnosis_history: list[str] = field(default_factory=list)  # Diagnosis.klass per step
    score: tuple = ()

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "parent_id": self.parent_id,
            "workdir": str(self.workdir),
            "src_dir": str(self.src_dir),
            "csim_status": self.csim_status,
            "csim_pass": self.csim_pass,
            "csynth_pass": self.csynth_pass,
            "csynth_status": self.csynth_status,
            "csynth_metrics": self.csynth_metrics,
            "impl_pass": self.impl_pass,
            "impl_status": self.impl_status,
            "impl_metrics": self.impl_metrics,
            "objective": self.objective,
            "throughput_target": self.throughput_target,
            "budget_spent": self.budget_spent,
            "diagnosis_history": self.diagnosis_history,
            "score": list(self.score),
        }
