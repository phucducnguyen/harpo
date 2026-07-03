#!/usr/bin/env python3
"""Canonical ablation TABLE builder — ONE source of truth for RESULTS.md/PAPER.md.

Reads every committed optimize-log JSON under ``docs/ablations/canonical/`` (one
file per ``<task>__<arm>`` arm, written by ``run_ablation.py``) and emits a single
GitHub-markdown table + matching CSV. RESULTS.md and PAPER.md should both render
from these artifacts, so the two documents can never disagree about a number.

This module is PURE with respect to Vitis/LLM: it only reads JSON logs and calls
``harpo.area`` for the derived area/ADP columns. The per-row derivations live
as small free functions at the top so they are directly unit-testable (see
``tests/test_ablation_table.py``) without writing any real run.

Layout (each JSON is the dict returned by ``agent.run_optimize``):

    task_id, phase, steps, baseline_metrics, best_candidate, best_metrics,
    improved, budget (snapshot), tokens ({prompt,completion,total}_tokens),
    events (probe event carries event=="probe", key "target"), candidates
    (Candidate.to_dict list).

Run::

    python3 scripts/ablation_table.py
    python3 scripts/ablation_table.py --canonical-dir docs/ablations/canonical
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

# Allow `python3 scripts/ablation_table.py` from anywhere (repo root not on path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harpo.area import adp, area_score  # noqa: E402

# ---------------------------------------------------------------------------
# Fixed ordering — hand-built kernels first, then PolyBench.
# ---------------------------------------------------------------------------
HAND_BUILT = ("mac8", "stencil3", "unroll8", "matmul", "conv2d")
POLYBENCH = ("gemm", "atax", "bicg")

# The arm label -> Method string mapping. ``recipe`` is split below by objective.
_ARM_ORDER = ("recipe", "speed_first", "llm")

COLUMNS = (
    "Kernel", "Category", "TargetSource", "Target", "Method", "Correct",
    "interval_max", "latency", "LUT", "FF", "BRAM", "DSP",
    "area_score", "ADP", "ToolCalls", "Tokens", "Accepted", "Reason",
)

_DASH = "—"


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested directly)
# ---------------------------------------------------------------------------
def category_for(task_id: str) -> str:
    """``hand-built`` for the five demo kernels, ``PolyBench`` for the three
    polybench-derived ones, else ``other``. Substring match on the task_id."""
    tid = task_id or ""
    for key in HAND_BUILT:
        if key in tid:
            return "hand-built"
    for key in POLYBENCH:
        if key in tid:
            return "PolyBench"
    return "other"


def _kernel_rank(task_id: str) -> tuple[int, int, str]:
    """Sort key: hand-built kernels (in HAND_BUILT order) before PolyBench
    (in POLYBENCH order); anything else last, alphabetically."""
    tid = task_id or ""
    for i, key in enumerate(HAND_BUILT):
        if key in tid:
            return (0, i, tid)
    for i, key in enumerate(POLYBENCH):
        if key in tid:
            return (1, i, tid)
    return (2, 0, tid)


def probe_target(log: dict) -> float | None:
    """The probe-derived ``throughput_target`` from the run's events, or None.

    ``run_optimize`` records exactly one event with ``event=="probe"`` carrying
    the derived ceiling under the key ``"target"``. Returns None when the spec
    hand-set a target (no probe ran) or the probe never fired."""
    for ev in log.get("events") or []:
        if isinstance(ev, dict) and ev.get("event") == "probe":
            t = ev.get("target")
            if isinstance(t, (int, float)) and not isinstance(t, bool):
                return float(t)
    return None


def arm_objective(log: dict) -> str | None:
    """The objective that arm ran under, read off the best/first candidate."""
    cands = log.get("candidates") or []
    if cands and isinstance(cands[0], dict):
        return cands[0].get("objective")
    return None


def arm_target(log: dict) -> float | None:
    """The throughput_target in effect for this arm.

    Prefer the candidate's recorded ``throughput_target`` (it is stamped from the
    task, post-probe); fall back to the probe event. None means no target (e.g.
    a speed_first arm)."""
    cands = log.get("candidates") or []
    if cands and isinstance(cands[0], dict):
        t = cands[0].get("throughput_target")
        if isinstance(t, (int, float)) and not isinstance(t, bool):
            return float(t)
    return probe_target(log)


def target_source(log: dict, *, spec_has_target: bool | None = None) -> str:
    """Classify where this arm's target came from.

    - ``n/a``        — no target at all (e.g. the speed_first arm).
    - ``hand-set``   — the spec.json carried a ``throughput_target`` (no probe
                       event present, OR an explicit ``spec_has_target`` hint).
    - ``auto-derived`` — a probe ran and derived a target STRICTLY BELOW the
                       baseline interval_max (the probe found real headroom).
    - ``fallback``   — a probe ran but the derived target equals (>=) the
                       baseline interval_max (no probe candidate beat baseline).
    """
    target = arm_target(log)
    if target is None:
        return "n/a"

    probe = probe_target(log)
    # No probe event -> the target was hand-set in the spec.
    if probe is None:
        return "hand-set"
    if spec_has_target:
        return "hand-set"

    base_iv = _metric(log.get("baseline_metrics"), "interval_max")
    if base_iv is None:
        # Can't compare — a probe fired, treat as auto-derived.
        return "auto-derived"
    return "auto-derived" if probe < base_iv else "fallback"


def method_label(arm: str, log: dict) -> str:
    """Human method string for the arm row."""
    if arm == "llm":
        return "raw LLM"
    if arm == "speed_first":
        return "recipe (speed_first)"
    # recipe arm — name the objective it actually ran under.
    obj = arm_objective(log) or "satisfice_then_area"
    return f"recipe ({obj})"


def tool_calls(log: dict) -> int:
    """Total tool invocations for the arm = sum of budget.snapshot()['spent']
    counts (csim + csynth + llm_calls + any other accounted action)."""
    spent = ((log.get("budget") or {}).get("spent")) or {}
    total = 0
    for v in spent.values():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            total += int(v)
    return total


def total_tokens(log: dict) -> int:
    """``tokens.total_tokens`` (recipe/speed_first arms are 0)."""
    t = (log.get("tokens") or {}).get("total_tokens")
    return int(t) if isinstance(t, (int, float)) and not isinstance(t, bool) else 0


def accepted_mark(log: dict) -> str:
    """✓ when the arm beat baseline (``improved``), ✗ when baseline was kept."""
    return "✓" if log.get("improved") else "✗"


def reason_for(log: dict) -> str:
    """One short phrase explaining the arm's accept/reject outcome."""
    improved = bool(log.get("improved"))
    base_iv = _metric(log.get("baseline_metrics"), "interval_max")
    best_iv = _metric(log.get("best_metrics"), "interval_max")
    target = arm_target(log)

    if improved:
        if (target is not None and best_iv is not None and best_iv <= target):
            return "meets target, lowest area"
        return "kept best"
    # Not improved -> baseline kept. Distinguish over-area rejection from a flat
    # no-op (best == baseline metrics).
    if (base_iv is not None and best_iv is not None and best_iv != base_iv):
        return "over-area, rejected"
    return "no improvement, baseline kept"


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------
def _metric(metrics: dict | None, key: str):
    """A numeric metric value, or None (also None for bools / non-numbers)."""
    if not metrics:
        return None
    v = metrics.get(key)
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    return None


def best_metrics_of(log: dict) -> dict | None:
    """The best design's metrics: prefer ``best_metrics``, else look up
    ``best_candidate`` in ``candidates`` and use its ``csynth_metrics``."""
    bm = log.get("best_metrics")
    if bm:
        return bm
    best_id = log.get("best_candidate")
    if best_id:
        for c in log.get("candidates") or []:
            if isinstance(c, dict) and c.get("candidate_id") == best_id:
                return c.get("csynth_metrics")
    return None


def _round_sig(value, sig: int = 4):
    """Round to ``sig`` significant figures; pass None / non-numbers through."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value == 0:
        return 0.0
    from math import floor, log10
    digits = sig - 1 - floor(log10(abs(value)))
    return round(value, digits)


def _fmt(value) -> str:
    """Markdown/CSV cell text for a possibly-None numeric value."""
    if value is None:
        return _DASH
    if isinstance(value, float):
        # Trim trailing zeros on floats for readability.
        s = f"{value:.6g}"
        return s
    return str(value)


# ---------------------------------------------------------------------------
# Row construction
# ---------------------------------------------------------------------------
def _metric_cells(metrics: dict | None) -> dict:
    """The shared metric-derived cells for a baseline or best-design row."""
    iv = _metric(metrics, "interval_max")
    lat = _metric(metrics, "latency_worst")
    lut = _metric(metrics, "lut")
    ff = _metric(metrics, "ff")
    bram = _metric(metrics, "bram_18k")
    dsp = _metric(metrics, "dsp")
    a = area_score(metrics) if metrics else None
    d = adp(metrics) if metrics else None
    return {
        "interval_max": _fmt(iv),
        "latency": _fmt(lat),
        "LUT": _fmt(lut),
        "FF": _fmt(ff),
        "BRAM": _fmt(bram),
        "DSP": _fmt(dsp),
        "area_score": _fmt(_round_sig(a, 4)),
        "ADP": _fmt(d),
    }


def baseline_row(task_id: str, log: dict) -> dict:
    """The single shared ``baseline`` row for a task (correct by construction)."""
    metrics = log.get("baseline_metrics")
    row = {
        "Kernel": task_id,
        "Category": category_for(task_id),
        "TargetSource": _DASH,
        "Target": _DASH,
        "Method": "baseline",
        "Correct": "✓",
        "ToolCalls": _DASH,
        "Tokens": _DASH,
        "Accepted": _DASH,
        "Reason": _DASH,
    }
    row.update(_metric_cells(metrics))
    return row


def arm_row(task_id: str, arm: str, log: dict, *,
            spec_has_target: bool | None = None) -> dict:
    """One row for an arm's BEST design."""
    metrics = best_metrics_of(log)
    target = arm_target(log) if arm != "speed_first" else None
    row = {
        "Kernel": task_id,
        "Category": category_for(task_id),
        "TargetSource": target_source(log, spec_has_target=spec_has_target),
        "Target": _fmt(target),
        "Method": method_label(arm, log),
        "Correct": "✓",
        "ToolCalls": str(tool_calls(log)),
        "Tokens": str(total_tokens(log)),
        "Accepted": accepted_mark(log),
        "Reason": reason_for(log),
    }
    row.update(_metric_cells(metrics))
    return row


# ---------------------------------------------------------------------------
# Loading + assembly
# ---------------------------------------------------------------------------
def _parse_name(path: Path) -> tuple[str, str] | None:
    """Split ``<task>__<arm>.json`` -> (task_id, arm). None for stray files."""
    stem = path.stem
    if "__" not in stem:
        return None
    task_id, _, arm = stem.partition("__")
    if not task_id or not arm:
        return None
    return task_id, arm


def load_logs(canonical_dir: Path) -> dict[str, dict[str, dict]]:
    """Map ``task_id -> {arm -> log dict}`` from every canonical JSON.

    TABLE.* are skipped; only ``<task>__<arm>.json`` files are read. A file that
    won't parse is reported to stderr and skipped (the table is best-effort)."""
    out: dict[str, dict[str, dict]] = {}
    for path in sorted(canonical_dir.glob("*.json")):
        parsed_name = _parse_name(path)
        if parsed_name is None:
            continue
        task_id, arm = parsed_name
        try:
            log = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"warning: skipping {path.name}: {exc}", file=sys.stderr)
            continue
        out.setdefault(task_id, {})[arm] = log
    return out


def _spec_has_target(canonical_dir: Path, task_id: str) -> bool | None:
    """Best-effort: did the task's spec.json hand-set a ``throughput_target``?

    Reads ``tasks/<task_id>/spec.json`` relative to the repo root when present.
    Returns None when the spec can't be found (caller then relies purely on the
    probe-event signal)."""
    repo_root = Path(__file__).resolve().parent.parent
    spec = repo_root / "tasks" / task_id / "spec.json"
    try:
        data = json.loads(spec.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    tgt = data.get("throughput_target")
    return isinstance(tgt, (int, float)) and not isinstance(tgt, bool)


def build_rows(logs: dict[str, dict[str, dict]],
               canonical_dir: Path | None = None) -> list[dict]:
    """All table rows, sorted by fixed kernel order; baseline row before its arms.

    For each task: ONE baseline row (deduped across that task's arms — they share
    a baseline), then one row per arm's best design in ``_ARM_ORDER``."""
    rows: list[dict] = []
    for task_id in sorted(logs, key=_kernel_rank):
        arms = logs[task_id]
        # The baseline is shared across all arms of a task: pick any arm that has
        # baseline_metrics so the single baseline row is deduplicated.
        base_log = None
        for arm in _ARM_ORDER:
            if arm in arms and arms[arm].get("baseline_metrics") is not None:
                base_log = arms[arm]
                break
        if base_log is None:
            # No arm recorded a baseline — still emit a baseline row from any arm
            # so the table is structurally complete.
            base_log = next(iter(arms.values()))
        rows.append(baseline_row(task_id, base_log))

        spec_flag = (_spec_has_target(canonical_dir, task_id)
                     if canonical_dir is not None else None)
        for arm in _ARM_ORDER:
            if arm in arms:
                rows.append(arm_row(task_id, arm, arms[arm],
                                    spec_has_target=spec_flag))
    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_markdown(rows: list[dict]) -> str:
    lines = []
    lines.append("| " + " | ".join(COLUMNS) + " |")
    lines.append("|" + "|".join(["---"] * len(COLUMNS)) + "|")
    for row in rows:
        cells = [str(row.get(c, _DASH)) for c in COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def render_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in COLUMNS})
    return buf.getvalue()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    default_dir = repo_root / "docs" / "ablations" / "canonical"

    p = argparse.ArgumentParser(
        description="Build the canonical ablation table (markdown + CSV) from "
                    "committed optimize-log JSON artifacts.")
    p.add_argument("--canonical-dir", default=str(default_dir),
                   help="directory of <task>__<arm>.json logs "
                        "(default docs/ablations/canonical/)")
    p.add_argument("--no-write", action="store_true",
                   help="print the markdown table only; do not write TABLE.md/.csv")
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

    rows = build_rows(logs, canonical_dir=canonical_dir)
    md = render_markdown(rows)
    print(md)

    if not args.no_write:
        (canonical_dir / "TABLE.md").write_text(md)
        (canonical_dir / "TABLE.csv").write_text(render_csv(rows))
        print(f"wrote {canonical_dir / 'TABLE.md'} and "
              f"{canonical_dir / 'TABLE.csv'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
