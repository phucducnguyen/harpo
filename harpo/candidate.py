"""Candidate Manager: give each attempt an isolated copy of the kernel source.

Patches edit a candidate's private ``src/`` copy under ``runs/<task_id>/<id>/``
so the original task bundle is never mutated. A candidate's TaskContext "view"
repoints ``src_dir``/``src_files`` at that copy, letting the runner compile the
edited source while the (un-edited) testbench stays at its original path.

Scoring is lexicographic and correctness-dominated: a candidate that passes
csim always beats one that does not, regardless of any later PPA dimensions.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

from . import store
from .area import area_score, adp
from .models import Candidate
from .task import TaskContext


class CandidateManager:
    """Mints and forks candidates, each with an isolated editable source copy."""

    def __init__(self, base_task: TaskContext) -> None:
        self.base_task = base_task

    def create_initial(self, candidate_id: str = "cand_0000") -> Candidate:
        """Create the root candidate by copying the task's source files in."""
        workdir = store.candidate_dir(self.base_task.task_id, candidate_id)
        src_dir = workdir / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        for f in self.base_task.src_files:
            shutil.copy2(f, src_dir / Path(f).name)
        return Candidate(
            candidate_id=candidate_id,
            workdir=workdir,
            src_dir=src_dir,
            parent_id=None,
            objective=self.base_task.objective,
            throughput_target=self.base_task.throughput_target,
        )

    def fork(self, parent: Candidate, candidate_id: str) -> Candidate:
        """Branch a new candidate from ``parent``'s current edited source copy."""
        workdir = store.candidate_dir(self.base_task.task_id, candidate_id)
        src_dir = workdir / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(parent.src_dir.iterdir()):
            if f.is_file():
                shutil.copy2(f, src_dir / f.name)
        return Candidate(
            candidate_id=candidate_id,
            workdir=workdir,
            src_dir=src_dir,
            parent_id=parent.candidate_id,
            diagnosis_history=list(parent.diagnosis_history),
            objective=self.base_task.objective,
            throughput_target=self.base_task.throughput_target,
        )

    def task_view(self, cand: Candidate) -> TaskContext:
        """A TaskContext like ``base_task`` but pointed at the candidate's copy.

        ``src_dir``/``src_files`` are repointed at the candidate's editable copy;
        ``tb_files`` keep their original paths (the testbench is never copied or
        edited). Pass the result to ``runner.run_stage(view, "csim", cand.workdir)``
        to compile the candidate's edited source against the real testbench.
        """
        src_files = [cand.src_dir / Path(p).name for p in self.base_task.src_files]
        return dataclasses.replace(
            self.base_task,
            src_dir=cand.src_dir,
            src_files=src_files,
        )

    def sources_dict(self, cand: Candidate) -> dict[str, str]:
        """Map each source filename (relative to ``cand.src_dir``) to its text."""
        out: dict[str, str] = {}
        for f in sorted(cand.src_dir.iterdir()):
            if f.is_file():
                out[f.name] = f.read_text()
        return out


# ---------------------------------------------------------------------------
# Scoring — lexicographic, correctness dominates
# ---------------------------------------------------------------------------
def correctness_tier(cand: Candidate) -> int:
    """Correctness rung: 0=csim unknown/fail, 1=csim pass, 2=csim+csynth pass.

    (Higher rungs for cosim/hw land when those backends do.)
    """
    if cand.csim_pass and cand.csynth_pass:
        return 2
    if cand.csim_pass:
        return 1
    return 0


def score(cand: Candidate) -> tuple:
    """Compute a sortable score (higher is better) and cache it on ``cand``.

    Lexicographic and correctness-dominated: a tier-2 (csim+csynth) candidate
    always outranks a tier-1 one regardless of PPA. Within a tier, the OBJECTIVE
    knob (``cand.objective``) selects the ordering.

    THROUGHPUT IS SCORED ON ``interval_max`` (the design-level initiation
    interval, always reported), NOT per-loop ``ii``. ``ii`` is kept in
    csynth_metrics as diagnostic data only and is never the primary throughput
    term — a fully-unrolled loop reports ``ii = None``, which would sort as 0
    and spuriously BEAT a real ``ii >= 1``, once rewarding over-unrolling
    (interval_max 3073 vs a 1024 baseline). interval_max is monotone and avoids
    that trap.

    Objectives (enum):

        "speed_first":        (tier, iv, lw, na, -steps)
            throughput (interval_max), then latency, then area, then steps.

        "area_first":         (tier, na, iv, -steps)
            smallest area first, throughput as tiebreak.

        "adp":                (tier, nad, na, -steps)
            best area-delay product first, then area.

        "satisfice_then_area" (default) and "pareto_report":
            meet a throughput target (interval_max <= throughput_target),
            THEN minimize area. Among candidates that meet the target, rank by
            area; candidates that miss the target rank below all that meet it
            and are driven on throughput first. With no usable target this
            degrades to a speed_first-style ordering with an area tiebreak (the
            proper recipe-only target probe is a deferred next step).

    Missing metrics sort as 0 (no worse than an unsynthesized peer). ``area_score``
    / ``adp`` returning None likewise contribute 0. All candidates compared by
    ``best()`` share the same objective (it comes from the task), so tuple
    lengths are consistent within a run; each branch still uses a fixed length.
    """
    m = cand.csynth_metrics or {}

    def neg(key):  # lower-is-better raw metric -> negate so higher score = better
        v = m.get(key)
        return -v if isinstance(v, (int, float)) else 0

    a = area_score(m)
    na = -a if isinstance(a, (int, float)) else 0   # lower area -> higher score
    ad = adp(m)
    nad = -ad if isinstance(ad, (int, float)) else 0

    iv = neg("interval_max")        # throughput, on design-level interval_max
    lw = neg("latency_worst")
    steps = len(cand.diagnosis_history)

    obj = cand.objective
    if obj == "area_first":
        s = (correctness_tier(cand), na, iv, -steps)
    elif obj == "adp":
        s = (correctness_tier(cand), nad, na, -steps)
    elif obj in ("satisfice_then_area", "pareto_report"):
        tgt = cand.throughput_target
        ivmax = m.get("interval_max")
        if isinstance(tgt, (int, float)) and isinstance(ivmax, (int, float)):
            meets = 1 if ivmax <= tgt else 0
            if meets:
                # met target -> rank by area, then throughput, then adp
                ppa = (1, na, iv, nad)
            else:
                # missed target -> drive throughput first, then area, then adp
                ppa = (0, iv, na, nad)
        else:
            # no usable target -> behaves like speed_first with an area tiebreak
            # (the proper recipe-only target probe is a deferred next step).
            # Exposed as a 4-tuple so lengths stay consistent with the gated case.
            ppa = (1, iv, na, nad)
        s = (correctness_tier(cand), *ppa, -steps)
    else:  # "speed_first" (and legacy throughput/latency, folded in at load)
        s = (correctness_tier(cand), iv, lw, na, -steps)

    cand.score = s
    return s


def best(cands: list[Candidate]) -> Candidate | None:
    """Return the highest-scoring candidate, or None if the list is empty."""
    if not cands:
        return None
    return max(cands, key=score)


def pareto_front(cands: list[Candidate]) -> list[Candidate]:
    """Non-dominated correct candidates on the (interval_max, area_score) plane.

    Lower is better on both axes. Candidate X dominates Y iff X is <= Y on both
    coordinates and < on at least one. Returns the correct (csim+csynth pass)
    candidates that nothing else dominates. Defensive: any candidate missing
    either coordinate is skipped. Supports ``pareto_report`` mode's reporting.
    """
    pts: list[tuple[Candidate, float, float]] = []
    for c in cands:
        if not (c.csim_pass and c.csynth_pass):
            continue
        m = c.csynth_metrics or {}
        iv = m.get("interval_max")
        ar = area_score(m)
        if not isinstance(iv, (int, float)) or not isinstance(ar, (int, float)):
            continue
        pts.append((c, float(iv), float(ar)))

    front: list[Candidate] = []
    for c, iv, ar in pts:
        dominated = False
        for other, oiv, oar in pts:
            if other is c:
                continue
            if oiv <= iv and oar <= ar and (oiv < iv or oar < ar):
                dominated = True
                break
        if not dominated:
            front.append(c)
    return front
