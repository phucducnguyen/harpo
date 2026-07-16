"""HARPO CLI.

  python -m harpo run    <task_dir> --stage csim [--backend gpp]
  python -m harpo repair <task_dir> [--provider mock,ollama] [--max-steps N]

`run` executes a single stage. `repair` runs the closed-loop repair agent.

Exit codes: 0 = pass/repaired, 1 = fail/not-repaired, 2 = tool unavailable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import store
from .agent import run_optimize, run_pipeline, run_repair
from .parser import parse_csim, parse_csynth, parse_impl
from .runner import run_stage
from .task import load_task

PARSERS = {"csim": parse_csim, "csynth": parse_csynth, "impl": parse_impl}


def cmd_run(args) -> int:
    task = load_task(args.task_dir)
    out_dir = store.candidate_dir(task.task_id, args.candidate)

    raw = run_stage(task, args.stage, out_dir, backend=args.backend)
    parse_fn = PARSERS.get(args.stage)
    parsed = parse_fn(raw) if parse_fn else {"stage": args.stage, "status": "no_parser"}

    store.write_run(task.task_id, args.candidate, raw, parsed)

    print(json.dumps(parsed, indent=2))
    print(f"\n[task] {task.task_id}  [evidence] {out_dir}", file=sys.stderr)

    if parsed.get("status") == "tool_unavailable":
        return 2
    return 0 if parsed.get("pass") else 1


def _build_providers(task_dir: str, names: list[str]) -> list:
    from .patch_engine import MockProvider, OllamaProvider
    from .recipes import RecipeProvider

    provs = []
    for n in names:
        if n == "mock":
            edits = []
            mp = Path(task_dir) / "mock_patch.json"
            if mp.exists():
                edits = [tuple(e) for e in json.loads(mp.read_text())]
            provs.append(MockProvider(edits))
        elif n == "ollama":
            provs.append(OllamaProvider())
        elif n == "recipe":
            provs.append(RecipeProvider())
        else:
            raise SystemExit(
                f"unknown provider: {n} (use mock, recipe, and/or ollama)")
    return provs


def cmd_repair(args) -> int:
    task = load_task(args.task_dir)
    names = [s.strip() for s in args.provider.split(",") if s.strip()]
    providers = _build_providers(args.task_dir, names)

    result = run_repair(task, providers, backend=args.backend,
                        max_steps=args.max_steps)

    summary = {k: result[k] for k in
               ("task_id", "steps", "repaired", "best_candidate", "budget")}
    print(json.dumps(summary, indent=2))
    print(f"\n[repair] {'REPAIRED' if result['repaired'] else 'NOT repaired'} "
          f"in {result['steps']} step(s) via {names}  log={result['log_path']}",
          file=sys.stderr)
    return 0 if result["repaired"] else 1


def cmd_optimize(args) -> int:
    task = load_task(args.task_dir)
    names = [s.strip() for s in args.provider.split(",") if s.strip()]
    providers = _build_providers(args.task_dir, names)

    result = run_optimize(
        task, providers, csim_backend=args.csim_backend,
        synth_backend=args.synth_backend, max_steps=args.max_steps,
        patience=args.patience, impl_verify=args.impl_verify,
    )

    summary = {k: result[k] for k in
               ("task_id", "steps", "improved", "best_candidate",
                "winner_fidelity", "best_candidate_estimate",
                "baseline_metrics", "best_metrics", "best_impl_metrics",
                "budget")}
    print(json.dumps(summary, indent=2))
    print(f"\n[optimize] {'IMPROVED' if result['improved'] else 'no improvement'} "
          f"in {result['steps']} step(s) via {names}  log={result['log_path']}",
          file=sys.stderr)
    return 0 if result["improved"] else 1


def cmd_pipeline(args) -> int:
    task = load_task(args.task_dir)
    rep_names = [s.strip() for s in args.repair_provider.split(",") if s.strip()]
    opt_names = [s.strip() for s in args.optimize_provider.split(",") if s.strip()]
    repair_providers = _build_providers(args.task_dir, rep_names)
    optimize_providers = _build_providers(args.task_dir, opt_names)

    result = run_pipeline(
        task, repair_providers, optimize_providers,
        repair_backend=args.repair_backend, csim_backend=args.csim_backend,
        synth_backend=args.synth_backend, max_repair_steps=args.max_repair_steps,
        max_optimize_steps=args.max_optimize_steps, patience=args.patience,
        impl_verify=args.impl_verify,
    )

    summary = {k: result.get(k) for k in
               ("task_id", "repaired", "improved", "budget", "tokens")}
    print(json.dumps(summary, indent=2))
    verdict = ("REPAIRED+IMPROVED" if result["repaired"] and result["improved"]
               else "REPAIRED (no PPA gain)" if result["repaired"]
               else "NOT repaired")
    print(f"\n[pipeline] {verdict}  log={result['log_path']}", file=sys.stderr)
    return 0 if result["repaired"] else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="harpo")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run one stage on a task")
    r.add_argument("task_dir")
    r.add_argument("--stage", default="csim", choices=["csim", "csynth", "impl"])
    r.add_argument("--backend", default="gpp", choices=["gpp", "vitis_hls"])
    r.add_argument("--candidate", default="cand_0000")
    r.set_defaults(func=cmd_run)

    rp = sub.add_parser("repair", help="run the closed-loop repair agent")
    rp.add_argument("task_dir")
    rp.add_argument("--provider", default="mock,ollama",
                    help="comma-separated provider order: mock,ollama")
    rp.add_argument("--backend", default="gpp", choices=["gpp"])
    rp.add_argument("--max-steps", type=int, default=12, dest="max_steps")
    rp.set_defaults(func=cmd_repair)

    op = sub.add_parser("optimize",
                        help="run the PPA optimization loop on a correct design")
    op.add_argument("task_dir")
    op.add_argument("--provider", default="recipe,ollama",
                    help="comma-separated provider order (default: recipe,ollama "
                         "— precise deterministic recipes first, LLM for the tail)")
    op.add_argument("--csim-backend", default="gpp", choices=["gpp"],
                    dest="csim_backend",
                    help="backend for the correctness re-verify (default gpp)")
    op.add_argument("--synth-backend", default="vitis_hls", choices=["vitis_hls"],
                    dest="synth_backend",
                    help="backend for synthesis/PPA (default vitis_hls)")
    op.add_argument("--max-steps", type=int, default=8, dest="max_steps")
    op.add_argument("--patience", type=int, default=2,
                    help="stop after N consecutive non-improvements")
    op.add_argument("--impl-verify", type=int, default=None, dest="impl_verify",
                    help="post-route-verify the top K candidates + baseline and "
                         "pick the winner from MEASURED PPA (0 = off; default: "
                         "the task's constraints.target.impl_verify_top_k)")
    op.set_defaults(func=cmd_optimize)

    pl = sub.add_parser("pipeline",
                        help="repair to correctness, then optimize PPA "
                             "(one shared per-task budget)")
    pl.add_argument("task_dir")
    pl.add_argument("--repair-provider", default="mock,ollama",
                    dest="repair_provider",
                    help="provider order for the repair phase (default mock,ollama)")
    pl.add_argument("--optimize-provider", default="recipe,ollama",
                    dest="optimize_provider",
                    help="provider order for the optimize phase (default recipe,ollama)")
    pl.add_argument("--repair-backend", default="gpp", choices=["gpp"],
                    dest="repair_backend")
    pl.add_argument("--csim-backend", default="gpp", choices=["gpp"],
                    dest="csim_backend")
    pl.add_argument("--synth-backend", default="vitis_hls", choices=["vitis_hls"],
                    dest="synth_backend")
    pl.add_argument("--max-repair-steps", type=int, default=12,
                    dest="max_repair_steps")
    pl.add_argument("--max-optimize-steps", type=int, default=8,
                    dest="max_optimize_steps")
    pl.add_argument("--patience", type=int, default=2,
                    help="stop optimize after N consecutive non-improvements")
    pl.add_argument("--impl-verify", type=int, default=None, dest="impl_verify",
                    help="post-route-verify the top K candidates + baseline and "
                         "pick the winner from MEASURED PPA (0 = off; default: "
                         "the task's constraints.target.impl_verify_top_k)")
    pl.set_defaults(func=cmd_pipeline)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
