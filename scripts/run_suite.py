#!/usr/bin/env python3
"""
run_suite.py — HARPO evidence-aggregation harness.

Reads the JSON logs that HARPO already writes under runs/<task_id>/ and
aggregates them into clean tables for the FPT'26 paper:

  - a markdown table   (stdout + runs/SUITE.md)
  - a CSV              (runs/SUITE.csv)
  - a token-consumption-by-phase summary (repair vs optimize)
  - a totals footer (tasks, tokens, tool calls)

Tasks are discovered dynamically by globbing tasks/*/spec.json. For each task
we read whatever logs exist (optimize_log.json / repair_log.json /
pipeline_log.json) and merge them into one row.

Default (no flag) = aggregate existing logs only — does NOT run Vitis.

Optional --run mode shells out to `python3 -m harpo optimize/pipeline ...`
to (re)generate the logs before aggregating. It is NOT run by default and needs
a working Vitis HLS install.

stdlib only (json, argparse, csv, pathlib, glob, subprocess, sys).
"""

import argparse
import csv
import glob
import json
import subprocess
import sys
from pathlib import Path

# Repo root = parent of this script's directory (scripts/).
REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "tasks"
RUNS_DIR = REPO_ROOT / "runs"

DASH = "—"

# Columns, in order. (key, header)
COLUMNS = [
    ("task", "task"),
    ("phases", "phase(s)"),
    ("repaired", "repaired"),
    ("improved", "improved"),
    ("ii", "II (base→best)"),
    ("latency", "latency (base→best)"),
    ("lut", "LUT (base→best)"),
    ("ff", "FF (base→best)"),
    ("fmax", "Fmax"),
    ("steps", "steps"),
    ("tokens", "tokens(P/C/total)"),
    ("budget", "budget spent (csim/csynth/llm)"),
]


def discover_tasks():
    """Return [(task_id, top_function, spec_path)] sorted by task_id."""
    out = []
    for spec_path in sorted(glob.glob(str(TASKS_DIR / "*" / "spec.json"))):
        try:
            with open(spec_path) as f:
                spec = json.load(f)
        except (OSError, ValueError):
            continue
        tid = spec.get("task_id") or Path(spec_path).parent.name
        top = spec.get("top_function", DASH)
        out.append((tid, top, spec_path))
    out.sort(key=lambda t: t[0])
    return out


def load_json(path):
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def fmt(v):
    """Render a scalar, using a dash for None/missing."""
    if v is None:
        return DASH
    return str(v)


def fmt_pair(base, best):
    """Render a base→best transition, dashing missing sides."""
    if base is None and best is None:
        return DASH
    if base == best and base is not None:
        return str(base)
    return "{}→{}".format(fmt(base), fmt(best))


def metric(d, key):
    """Pull a metric from a metrics dict, tolerating None dicts."""
    if not isinstance(d, dict):
        return None
    return d.get(key)


def budget_str(budget):
    """Render budget.spent as csim/csynth/llm."""
    if not isinstance(budget, dict):
        return DASH
    spent = budget.get("spent", {}) or {}
    csim = spent.get("csim", 0)
    csynth = spent.get("csynth", 0)
    llm = spent.get("llm_calls", 0)
    return "{}/{}/{}".format(csim, csynth, llm)


def tokens_str(tokens):
    if not isinstance(tokens, dict):
        return DASH
    p = tokens.get("prompt_tokens", 0)
    c = tokens.get("completion_tokens", 0)
    t = tokens.get("total_tokens", 0)
    return "{}/{}/{}".format(p, c, t)


def tokens_triple(tokens):
    if not isinstance(tokens, dict):
        return (0, 0, 0)
    return (
        tokens.get("prompt_tokens", 0) or 0,
        tokens.get("completion_tokens", 0) or 0,
        tokens.get("total_tokens", 0) or 0,
    )


def budget_calls(budget):
    """Sum of all budget.spent values (total tool calls)."""
    if not isinstance(budget, dict):
        return 0
    spent = budget.get("spent", {}) or {}
    return sum(v for v in spent.values() if isinstance(v, (int, float)))


def aggregate_task(task_id, top, task_dir):
    """
    Merge optimize/repair/pipeline logs for one task into a single row dict
    plus a per-phase token accumulator. Returns None if no logs exist.
    """
    opt = load_json(task_dir / "optimize_log.json")
    rep = load_json(task_dir / "repair_log.json")
    pipe = load_json(task_dir / "pipeline_log.json")

    if opt is None and rep is None and pipe is None:
        return None

    phases = []
    if rep is not None:
        phases.append("repair")
    if opt is not None:
        phases.append("optimize")
    if pipe is not None:
        phases.append("pipeline")

    # ---- repaired / improved ---------------------------------------------
    repaired = None
    improved = None
    if pipe is not None:
        repaired = pipe.get("repaired", repaired)
        improved = pipe.get("improved", improved)
    if rep is not None:
        repaired = rep.get("repaired", repaired)
    if opt is not None:
        improved = opt.get("improved", improved)

    # ---- PPA metrics (prefer optimize; fall back to pipeline.optimize) ----
    opt_block = opt
    if opt_block is None and isinstance(pipe, dict):
        opt_block = pipe.get("optimize")
    base = metric_block(opt_block, "baseline_metrics")
    best = metric_block(opt_block, "best_metrics")

    ii = fmt_pair(metric(base, "ii"), metric(best, "ii"))
    # latency_worst is the metric the lexicographic score ranks on; report it so
    # the table matches the optimizer's decisions even when best != worst.
    latency = fmt_pair(metric(base, "latency_worst"), metric(best, "latency_worst"))
    lut = fmt_pair(metric(base, "lut"), metric(best, "lut"))
    ff = fmt_pair(metric(base, "ff"), metric(best, "ff"))

    # Fmax: best if available, else baseline.
    fmax = metric(best, "fmax_mhz")
    if fmax is None:
        fmax = metric(base, "fmax_mhz")

    # ---- steps (sum across phases that report it) -------------------------
    steps_total = 0
    have_steps = False
    for block in (rep, opt):
        if isinstance(block, dict) and block.get("steps") is not None:
            steps_total += block.get("steps") or 0
            have_steps = True
    if isinstance(pipe, dict):
        for sub in ("repair", "optimize"):
            b = pipe.get(sub)
            if isinstance(b, dict) and b.get("steps") is not None and opt is None and rep is None:
                steps_total += b.get("steps") or 0
                have_steps = True
    steps = steps_total if have_steps else None

    # ---- tokens (sum across phases) + per-phase split --------------------
    rep_tokens = (0, 0, 0)
    opt_tokens = (0, 0, 0)
    if isinstance(rep, dict):
        rep_tokens = tokens_triple(rep.get("tokens"))
    if isinstance(opt, dict):
        opt_tokens = tokens_triple(opt.get("tokens"))
    if isinstance(pipe, dict):
        # pipeline may carry nested per-phase token blocks
        if isinstance(pipe.get("repair"), dict) and rep is None:
            rep_tokens = tokens_triple(pipe["repair"].get("tokens"))
        if isinstance(pipe.get("optimize"), dict) and opt is None:
            opt_tokens = tokens_triple(pipe["optimize"].get("tokens"))

    total_tokens = tuple(rep_tokens[i] + opt_tokens[i] for i in range(3))
    tokens_cell = "{}/{}/{}".format(*total_tokens)

    # ---- budget spent (sum across phases) --------------------------------
    spent_csim = spent_csynth = spent_llm = 0
    tool_calls = 0
    for block in (rep, opt):
        if isinstance(block, dict):
            b = block.get("budget")
            if isinstance(b, dict):
                sp = b.get("spent", {}) or {}
                spent_csim += sp.get("csim", 0) or 0
                spent_csynth += sp.get("csynth", 0) or 0
                spent_llm += sp.get("llm_calls", 0) or 0
                tool_calls += budget_calls(b)
    if opt is None and rep is None and isinstance(pipe, dict):
        b = pipe.get("budget")
        if isinstance(b, dict):
            sp = b.get("spent", {}) or {}
            spent_csim += sp.get("csim", 0) or 0
            spent_csynth += sp.get("csynth", 0) or 0
            spent_llm += sp.get("llm_calls", 0) or 0
            tool_calls += budget_calls(b)
    budget_cell = "{}/{}/{}".format(spent_csim, spent_csynth, spent_llm)

    row = {
        "task": task_id,
        "phases": "+".join(phases) if phases else DASH,
        "repaired": fmt(repaired),
        "improved": fmt(improved),
        "ii": ii,
        "latency": latency,
        "lut": lut,
        "ff": ff,
        "fmax": fmt(fmax),
        "steps": fmt(steps),
        "tokens": tokens_cell,
        "budget": budget_cell,
    }

    meta = {
        "rep_tokens": rep_tokens,
        "opt_tokens": opt_tokens,
        "total_tokens": total_tokens,
        "tool_calls": tool_calls,
        "has_repair": rep is not None or (isinstance(pipe, dict) and pipe.get("repair") is not None),
        "has_optimize": opt is not None or (isinstance(pipe, dict) and pipe.get("optimize") is not None),
    }
    return row, meta


def metric_block(block, key):
    """Get a metrics sub-dict from a phase log block (tolerant of None)."""
    if not isinstance(block, dict):
        return None
    return block.get(key)


def render_markdown(rows):
    headers = [h for (_, h) in COLUMNS]
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for r in rows:
        cells = [str(r.get(k, DASH)) for (k, _) in COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_csv(rows, path):
    headers = [k for (k, _) in COLUMNS]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([h for (_, h) in COLUMNS])
        for r in rows:
            w.writerow([r.get(k, "") for k in headers])


def run_harpo(task_id, mode):
    """Shell out to the harpo CLI to (re)generate logs. NOT run by default."""
    if mode == "pipeline":
        cmd = [sys.executable, "-m", "harpo", "pipeline", task_id, "--provider", "recipe"]
    else:
        cmd = [sys.executable, "-m", "harpo", "optimize", task_id, "--provider", "recipe"]
    print("[run] " + " ".join(cmd), file=sys.stderr)
    try:
        subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    except OSError as e:
        print("[run] failed to launch for {}: {}".format(task_id, e), file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Aggregate HARPO run logs into paper-ready tables."
    )
    ap.add_argument(
        "--run",
        action="store_true",
        help="Shell out to `python3 -m harpo ...` per task to (re)generate "
             "logs before aggregating. Needs Vitis HLS; NOT done by default.",
    )
    ap.add_argument(
        "--run-mode",
        choices=["optimize", "pipeline"],
        default="optimize",
        help="Which harpo subcommand --run invokes (default: optimize).",
    )
    ap.add_argument(
        "--tasks",
        default=None,
        help="Comma-separated task_ids to restrict to (default: all discovered).",
    )
    args = ap.parse_args(argv)

    tasks = discover_tasks()
    if not tasks:
        print("No tasks found under {}/*/spec.json".format(TASKS_DIR), file=sys.stderr)
        return 1

    if args.tasks:
        wanted = {t.strip() for t in args.tasks.split(",") if t.strip()}
        tasks = [t for t in tasks if t[0] in wanted]
        if not tasks:
            print("No discovered tasks matched --tasks={}".format(args.tasks), file=sys.stderr)
            return 1

    if args.run:
        for tid, _top, _spec in tasks:
            run_harpo(tid, args.run_mode)

    rows = []
    metas = []
    skipped = []
    for tid, _top, _spec in tasks:
        task_dir = RUNS_DIR / tid
        result = aggregate_task(tid, _top, task_dir)
        if result is None:
            skipped.append(tid)
            continue
        row, meta = result
        rows.append(row)
        metas.append(meta)

    if not rows:
        print("No tasks have logs yet under {}. Nothing to aggregate.".format(RUNS_DIR),
              file=sys.stderr)
        for tid in skipped:
            print("  skipped (no logs): {}".format(tid), file=sys.stderr)
        return 1

    # ---- markdown table ---------------------------------------------------
    md_table = render_markdown(rows)

    # ---- token-by-phase summary ------------------------------------------
    rep_total = [0, 0, 0]
    opt_total = [0, 0, 0]
    for m in metas:
        for i in range(3):
            rep_total[i] += m["rep_tokens"][i]
            opt_total[i] += m["opt_tokens"][i]
    grand_total = [rep_total[i] + opt_total[i] for i in range(3)]

    token_lines = []
    token_lines.append("## Token consumption by phase")
    token_lines.append("")
    token_lines.append("| phase | prompt | completion | total |")
    token_lines.append("| --- | --- | --- | --- |")
    token_lines.append("| repair | {} | {} | {} |".format(*rep_total))
    token_lines.append("| optimize | {} | {} | {} |".format(*opt_total))
    token_lines.append("| **all** | {} | {} | {} |".format(*grand_total))
    token_summary = "\n".join(token_lines)

    # ---- totals footer ----------------------------------------------------
    total_calls = sum(m["tool_calls"] for m in metas)
    footer = (
        "_Totals: {} task(s) aggregated · {} total tokens "
        "(P {} / C {}) · {} total tool calls (sum of budget.spent)._".format(
            len(rows), grand_total[2], grand_total[0], grand_total[1], total_calls
        )
    )

    skip_note = ""
    if skipped:
        skip_note = "\n_Skipped (no logs yet): {}_".format(", ".join(skipped))

    doc = "\n".join([
        "# HARPO suite results",
        "",
        md_table,
        "",
        footer + skip_note,
        "",
        token_summary,
        "",
    ])

    # ---- emit -------------------------------------------------------------
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    suite_md = RUNS_DIR / "SUITE.md"
    suite_csv = RUNS_DIR / "SUITE.csv"
    with open(suite_md, "w") as f:
        f.write(doc)
    write_csv(rows, suite_csv)

    print(doc)
    print("[written] {}".format(suite_md), file=sys.stderr)
    print("[written] {}".format(suite_csv), file=sys.stderr)
    if skipped:
        for tid in skipped:
            print("[skip] no logs yet: {}".format(tid), file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
