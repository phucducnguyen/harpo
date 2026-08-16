#!/usr/bin/env python3
"""Canonical ablation MATRIX driver — runs each arm, saves a log per arm.

Runs the HARPO optimize agent (via the API, NOT the CLI) across a fixed
ablation matrix and writes each run's full result dict to a stable canonical
path::

    docs/ablations/canonical/<task>__<arm>.json

``scripts/ablation_table.py`` then reads those logs into ONE markdown+CSV table
so RESULTS.md and PAPER.md render from the same source of truth.

THIS SCRIPT NEEDS REAL VITIS HLS — only the maintainer runs it (csynth uses the
``vitis_hls`` backend). ``ablation_table.py`` is the pure half that needs none.

The matrix (arm -> how it runs):

  recipe       provider ["recipe"], the task's OWN objective + target.
               All 8 tasks.
  llm          provider ["ollama"], the task's OWN objective + target.
               mac8_001, matmul_001, atax_001, gemm_001.
  speed_first  provider ["recipe"], objective forced to "speed_first",
               throughput_target forced to None. matmul_001 ONLY — exposes the
               Fix-2 delta (speed-first over-pushes area vs satisfice).

Run::

    python3 scripts/run_ablation.py                       # full matrix
    python3 scripts/run_ablation.py --only matmul_001
    python3 scripts/run_ablation.py --arms recipe,speed_first
    python3 scripts/run_ablation.py --overwrite   # REPLACE committed evidence
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import traceback
from pathlib import Path

# Allow `python3 scripts/run_ablation.py` from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harpo import cli  # noqa: E402
from harpo.agent import run_optimize  # noqa: E402
from harpo.task import load_task  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "tasks"
CANONICAL_DIR = REPO_ROOT / "docs" / "ablations" / "canonical"

# ---------------------------------------------------------------------------
# The matrix — (task_id, arm) pairs, in a stable order.
# ---------------------------------------------------------------------------
ALL_TASKS = (
    "mac8_001", "stencil3_001", "unroll8_001", "matmul_001", "conv2d_001",
    "gemm_001", "atax_001", "bicg_001",
)
LLM_TASKS = ("mac8_001", "matmul_001", "atax_001", "gemm_001")
SPEED_FIRST_TASKS = ("matmul_001",)

# arm label -> (provider names, objective override or None, force_target_none)
ARMS: dict[str, tuple[list[str], str | None, bool]] = {
    "recipe": (["recipe"], None, False),
    "llm": (["ollama"], None, False),
    "speed_first": (["recipe"], "speed_first", True),
}


def matrix(only: set[str] | None, arms: set[str] | None) -> list[tuple[str, str]]:
    """The (task_id, arm) worklist, filtered by ``--only`` / ``--arms``."""
    pairs: list[tuple[str, str]] = []
    for task_id in ALL_TASKS:
        pairs.append((task_id, "recipe"))
    for task_id in LLM_TASKS:
        pairs.append((task_id, "llm"))
    for task_id in SPEED_FIRST_TASKS:
        pairs.append((task_id, "speed_first"))

    out = []
    for task_id, arm in pairs:
        if only and task_id not in only:
            continue
        if arms and arm not in arms:
            continue
        out.append((task_id, arm))
    return out


def _build_task(task_id: str, arm: str):
    """Load the task and apply the arm's objective/target override."""
    task_dir = TASKS_DIR / task_id
    task = load_task(task_dir)
    _names, obj_override, force_target_none = ARMS[arm]
    changes: dict = {}
    if obj_override is not None:
        changes["objective"] = obj_override
    if force_target_none:
        changes["throughput_target"] = None
    if changes:
        task = dataclasses.replace(task, **changes)
    return task, task_dir


def _summary_line(task_id: str, arm: str, result: dict) -> str:
    """One-line per-run summary: best interval_max / lut + improved flag."""
    bm = result.get("best_metrics") or {}
    iv = bm.get("interval_max")
    lut = bm.get("lut")
    return (f"{task_id} {arm} -> best interval_max {iv} / lut {lut}, "
            f"improved={result.get('improved')}")


def run_arm(task_id: str, arm: str, *, overwrite: bool) -> str:
    """Run one (task, arm); write its log JSON.

    Returns "written" | "skipped" | "failed". ⚠️ These are THREE verdicts, not
    two: leaving committed evidence alone is the correct default outcome, and
    collapsing it into "not written" made the documented regeneration command
    exit 1 on every clean checkout.

    Robust: any failure (exception, tool_unavailable surfaced as a thrown error)
    is logged as a warning and the matrix continues.

    ⚠️ These files ARE the paper's evidence base, and the reproducibility
    appendix tells readers to run this script and then compare against them.
    Overwriting is therefore opt-IN, and a run that never reached synthesis is
    refused outright: without Vitis, run_optimize does not raise, it returns a
    degenerate result, which used to land on top of real committed evidence.
    """
    out_path = CANONICAL_DIR / f"{task_id}__{arm}.json"
    if out_path.exists() and not overwrite:
        print(f"skip (committed evidence exists): {task_id} {arm} -> "
              f"{out_path.name}  [--overwrite to replace]")
        return "skipped"

    names = ARMS[arm][0]
    try:
        task, task_dir = _build_task(task_id, arm)
        providers = cli._build_providers(str(task_dir), names)
        result = run_optimize(
            task, providers, csim_backend="gpp", synth_backend="vitis_hls")
        if not (result.get("baseline_metrics") or {}):
            print(f"REFUSED: {task_id} {arm} produced no baseline synthesis "
                  f"metrics (Vitis unavailable?) — {out_path.name} left "
                  f"untouched", file=sys.stderr)
            return "failed"
        # Strip the local log_path (machine-specific) before persisting.
        to_write = {k: v for k, v in result.items() if k != "log_path"}
        CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(to_write, indent=2))
        print(_summary_line(task_id, arm, result))
        print(f"  wrote {out_path}")
        return "written"
    except Exception as exc:  # noqa: BLE001 — one arm must never kill the matrix
        print(f"WARNING: {task_id} {arm} failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return "failed"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Run the canonical ablation matrix (needs real Vitis HLS) "
                    "and save one optimize-log JSON per arm.")
    p.add_argument("--only", default=None,
                   help="comma-separated task ids to include (default: all)")
    p.add_argument("--arms", default=None,
                   help="comma-separated arms to include: recipe,llm,speed_first")
    p.add_argument("--overwrite", action="store_true",
                   help="REPLACE committed canonical evidence for the selected "
                        "arms (default: existing files are left alone)")
    p.add_argument("--skip-existing", action="store_true",
                   help=argparse.SUPPRESS)  # now the default; accepted, no-op
    args = p.parse_args(argv)

    only = {s.strip() for s in args.only.split(",") if s.strip()} if args.only else None
    arms = {s.strip() for s in args.arms.split(",") if s.strip()} if args.arms else None
    if arms:
        unknown = arms - set(ARMS)
        if unknown:
            raise SystemExit(f"unknown arm(s): {sorted(unknown)} "
                             f"(use {','.join(ARMS)})")

    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    work = matrix(only, arms)
    if not work:
        print("nothing to run (check --only / --arms filters)", file=sys.stderr)
        return 1

    print(f"=== ablation matrix: {len(work)} run(s) -> {CANONICAL_DIR} ===")
    tally = {"written": 0, "skipped": 0, "failed": 0}
    for task_id, arm in work:
        tally[run_arm(task_id, arm, overwrite=args.overwrite)] += 1
    print(f"=== done: {tally['written']} written, {tally['skipped']} skipped "
          f"(evidence present), {tally['failed']} failed, of {len(work)} arm(s) ===")
    if tally["skipped"] and not tally["written"] and not tally["failed"]:
        print("=== nothing to do: every selected arm already has committed "
              "evidence. Pass --overwrite to regenerate it. ===")
    if tally["failed"]:
        # Only a genuine failure is nonzero. A skip is the safe default outcome,
        # not an error — the previous version exited 1 on a clean checkout and
        # left the reproducibility appendix with no working command.
        print(f"=== {tally['failed']} arm(s) FAILED ===", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
