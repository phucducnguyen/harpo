#!/usr/bin/env python3
"""Pareto / ADRS appendix view — an OPTIONAL secondary analysis of the logs.

This is a cheap, read-only companion to ``scripts/ablation_table.py``. It reads
the SAME committed optimize-log JSON under ``docs/ablations/canonical/`` (one
file per ``<task>__<arm>`` arm, written by ``run_ablation.py``) and projects each
kernel's design points onto the **(throughput, area)** plane to produce a
per-kernel Pareto frontier plus a small ADRS (Average Distance from Reference
Set) summary, rendered as markdown -> ``docs/ablations/canonical/PARETO.md``.

It does NOT touch the main results path (RESULTS.md / PAPER.md / TABLE.*): it
only writes its own ``PARETO.md`` and prints to stdout. It is PURE with respect
to Vitis/LLM — it reads JSON and calls ``harpo.area.area_score``.

Design points per kernel: the shared **baseline** ``(interval_max, area_score)``
plus, for each arm, that arm's BEST design ``(interval_max, area_score)``. Lower
is better on both axes.

The ADRS formula (documented in ``adrs`` below): the reference Pareto set is the
non-dominated frontier of the UNION of all arms' points for the kernel. For a
query set Q (here, a single arm's one point), ADRS = mean over each reference
point r of the minimum, over q in Q, of the *relative* coordinate distance
``max(|q.iv-r.iv|/r.iv, |q.area-r.area|/r.area)`` — the standard min-relative
ADRS (Chebyshev / max-of-relative-coords variant). ADRS == 0 when the query set
covers the reference set exactly; larger means farther from the achievable best.

Run::

    python3 scripts/pareto_view.py
    python3 scripts/pareto_view.py --no-write
    python3 scripts/pareto_view.py --canonical-dir docs/ablations/canonical
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python3 scripts/pareto_view.py` from anywhere (repo root not on path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harpo.area import area_score  # noqa: E402

# Reuse the canonical loader + ordering + metric helpers so the two views read
# the exact same logs the same way (single source of truth for conventions).
from ablation_table import (  # noqa: E402
    _ARM_ORDER,
    _kernel_rank,
    best_metrics_of,
    load_logs,
    method_label,
)

_DASH = "—"


# ---------------------------------------------------------------------------
# Pure geometry helpers (unit-tested directly)
# ---------------------------------------------------------------------------
def dominates(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """True if point ``a`` dominates ``b`` on (interval_max, area_score).

    Lower is better on both coords. ``a`` dominates ``b`` iff ``a`` is <= ``b``
    on both coordinates AND strictly < on at least one.
    """
    return a[0] <= b[0] and a[1] <= b[1] and (a[0] < b[0] or a[1] < b[1])


def pareto_flags(points: list[tuple[float, float]]) -> list[bool]:
    """For each point, True if it is on the Pareto frontier (non-dominated).

    A point is dominated when any *other* point dominates it (see ``dominates``).
    Exact-duplicate points are all kept on the frontier (neither strictly beats
    the other). Pure point-based reimplementation of ``candidate.pareto_front``
    for use here, where we work from logs rather than Candidate objects.
    """
    flags: list[bool] = []
    for i, p in enumerate(points):
        dominated = False
        for j, q in enumerate(points):
            if i == j:
                continue
            if dominates(q, p):
                dominated = True
                break
        flags.append(not dominated)
    return flags


def reference_set(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The reference Pareto set: the non-dominated points of ``points``, deduped."""
    flags = pareto_flags(points)
    ref: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for p, keep in zip(points, flags):
        if keep and p not in seen:
            seen.add(p)
            ref.append(p)
    return ref


def _rel_dist(q: tuple[float, float], r: tuple[float, float]) -> float | None:
    """Relative (Chebyshev) distance from query ``q`` to reference ``r``.

    ``max(|q.iv-r.iv|/r.iv, |q.area-r.area|/r.area)``. None if either reference
    coordinate is 0 (no meaningful relative distance against a zero coordinate).
    """
    if r[0] == 0 or r[1] == 0:
        return None
    return max(abs(q[0] - r[0]) / r[0], abs(q[1] - r[1]) / r[1])


def adrs(query: list[tuple[float, float]],
         reference: list[tuple[float, float]]) -> float | None:
    """Average Distance from Reference Set (min-relative / Chebyshev variant).

    For each reference point ``r``, take the minimum relative distance from any
    query point ``q`` (``_rel_dist``); ADRS is the mean of those minima over the
    reference set. Returns 0.0 when ``query`` covers ``reference`` exactly, a
    positive number when ``query`` sits strictly worse, and None when neither
    set is usable (empty, or every reference point has a zero coordinate).
    """
    if not query or not reference:
        return None
    mins: list[float] = []
    for r in reference:
        cand = [d for d in (_rel_dist(q, r) for q in query) if d is not None]
        if cand:
            mins.append(min(cand))
    if not mins:
        return None
    return sum(mins) / len(mins)


# ---------------------------------------------------------------------------
# Point extraction from logs
# ---------------------------------------------------------------------------
def _point(metrics: dict | None) -> tuple[float, float] | None:
    """``(interval_max, area_score)`` for a metrics dict, or None if either is
    missing/non-numeric. Defensive: never raises on a malformed metrics blob."""
    if not metrics:
        return None
    iv = metrics.get("interval_max")
    if isinstance(iv, bool) or not isinstance(iv, (int, float)):
        return None
    ar = area_score(metrics)
    if ar is None:
        return None
    return (float(iv), float(ar))


def kernel_points(arms: dict[str, dict]) -> tuple[
        tuple[float, float] | None, dict[str, tuple[float, float]]]:
    """Extract a kernel's design points from its arm logs.

    Returns ``(baseline_point, {arm -> best_point})``. The baseline is shared
    across arms; we take it from the first arm (in ``_ARM_ORDER``) that records a
    usable ``baseline_metrics`` point. Arms whose best design lacks a usable
    point are simply omitted from the arm map.
    """
    baseline: tuple[float, float] | None = None
    for arm in _ARM_ORDER:
        log = arms.get(arm)
        if log is None:
            continue
        if baseline is None:
            baseline = _point(log.get("baseline_metrics"))
        if baseline is not None:
            break
    # Fall back to any arm if none of the ordered arms had a baseline point.
    if baseline is None:
        for log in arms.values():
            baseline = _point(log.get("baseline_metrics"))
            if baseline is not None:
                break

    arm_pts: dict[str, tuple[float, float]] = {}
    for arm in _ARM_ORDER:
        log = arms.get(arm)
        if log is None:
            continue
        pt = _point(best_metrics_of(log))
        if pt is not None:
            arm_pts[arm] = pt
    return baseline, arm_pts


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _fmt_num(v: float | None) -> str:
    if v is None:
        return _DASH
    return f"{v:.6g}"


def render_kernel(task_id: str, arms: dict[str, dict]) -> str:
    """Markdown for one kernel: the frontier table + an ADRS line per arm."""
    baseline, arm_pts = kernel_points(arms)

    # Labelled design rows: baseline first, then arms in canonical order.
    labelled: list[tuple[str, tuple[float, float]]] = []
    if baseline is not None:
        labelled.append(("baseline", baseline))
    for arm in _ARM_ORDER:
        if arm in arm_pts:
            labelled.append((method_label(arm, arms[arm]), arm_pts[arm]))

    lines: list[str] = [f"### {task_id}", ""]
    if not labelled:
        lines.append("_no usable (interval_max, area_score) design points_")
        lines.append("")
        return "\n".join(lines)

    points = [p for _, p in labelled]
    flags = pareto_flags(points)

    lines.append("| Design (arm/method) | interval_max | area_score | ADP | on-frontier? |")
    lines.append("|---|---|---|---|---|")
    for (label, (iv, ar)), on_front in zip(labelled, flags):
        adp_val = iv * ar
        lines.append(
            f"| {label} | {_fmt_num(iv)} | {_fmt_num(ar)} | {_fmt_num(adp_val)} "
            f"| {'✓' if on_front else _DASH} |"
        )
    lines.append("")

    # ADRS: reference = frontier of the union of all points; compare recipe vs
    # raw-LLM arm to that reference. Skip gracefully when an arm is absent.
    ref = reference_set(points)
    recipe_pt = arm_pts.get("recipe")
    llm_pt = arm_pts.get("llm")
    adrs_recipe = adrs([recipe_pt], ref) if recipe_pt is not None else None
    adrs_llm = adrs([llm_pt], ref) if llm_pt is not None else None

    if adrs_recipe is None and adrs_llm is None:
        lines.append("_ADRS: no recipe/LLM arm to score_")
    else:
        parts = []
        if adrs_recipe is not None:
            parts.append(f"recipe = {adrs_recipe:.4g}")
        if adrs_llm is not None:
            parts.append(f"raw LLM = {adrs_llm:.4g}")
        else:
            parts.append("raw LLM = (no LLM arm)")
        lines.append("ADRS (min-relative distance to the per-kernel reference "
                     "frontier; 0 = on it): " + ", ".join(parts))
    lines.append("")
    return "\n".join(lines)


def render_markdown(logs: dict[str, dict[str, dict]]) -> str:
    """The full PARETO.md body for all kernels, in canonical kernel order."""
    lines: list[str] = [
        "# Pareto / ADRS appendix",
        "",
        "_OPTIONAL secondary view. Generated by `scripts/pareto_view.py` from the "
        "same `docs/ablations/canonical/*.json` logs as the main ablation table. "
        "It does not feed RESULTS.md / PAPER.md._",
        "",
        "Each kernel's design points are the shared **baseline** plus each arm's "
        "**best** design, projected onto **(interval_max, area_score)** — lower is "
        "better on both. A point is on the frontier when nothing else is <= on "
        "both coords and < on at least one.",
        "",
        "**ADRS** = Average Distance from Reference Set (min-relative / Chebyshev "
        "variant): the reference set is the frontier of the union of all arms' "
        "points; for an arm we average, over each reference point, the relative "
        "distance `max(|Δiv|/iv, |Δarea|/area)`. 0 means the arm lands on the "
        "frontier; larger is farther from the achievable best.",
        "",
    ]
    for task_id in sorted(logs, key=_kernel_rank):
        lines.append(render_kernel(task_id, logs[task_id]))
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    default_dir = repo_root / "docs" / "ablations" / "canonical"

    p = argparse.ArgumentParser(
        description="Build the OPTIONAL Pareto/ADRS appendix (markdown) from the "
                    "committed optimize-log JSON artifacts. Secondary view; does "
                    "not touch RESULTS.md/PAPER.md.")
    p.add_argument("--canonical-dir", default=str(default_dir),
                   help="directory of <task>__<arm>.json logs "
                        "(default docs/ablations/canonical/)")
    p.add_argument("--no-write", action="store_true",
                   help="print the markdown only; do not write PARETO.md")
    args = p.parse_args(argv)

    canonical_dir = Path(args.canonical_dir)
    if not canonical_dir.is_dir():
        print(f"no canonical dir: {canonical_dir} "
              f"(run scripts/run_ablation.py first)", file=sys.stderr)
        return 1

    logs = load_logs(canonical_dir)
    if not logs:
        print(f"no <task>__<arm>.json logs in {canonical_dir}", file=sys.stderr)
        return 1

    md = render_markdown(logs)
    print(md)

    if not args.no_write:
        out = canonical_dir / "PARETO.md"
        out.write_text(md)
        print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
