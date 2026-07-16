"""Task loader: normalize a task bundle dir into one internal TaskContext.

A task dir holds spec.json (interface contract + file lists + policy),
constraints.json (tool/part/clock/resource limits), and budget.json
(per-tool invocation limits). The competition will supply its own bundles;
keep this tolerant of extra/missing fields.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TaskContext:
    task_id: str
    task_dir: Path
    top_function: str
    language: str
    src_files: list[Path]
    tb_files: list[Path]
    src_dir: Path
    tb_dir: Path
    clock_period_ns: float
    fpga_part: str
    policy: dict
    budget: dict
    objective: str = "satisfice_then_area"  # enum: speed_first | area_first | adp | satisfice_then_area | pareto_report
    throughput_target: float | None = None  # interval_max ceiling for satisfice_then_area; None = no explicit target
    include_dirs: list[Path] = field(default_factory=list)  # extra -I dirs for HOST csim only (vendored ap_int.h etc.); vitis uses its own shipped headers
    impl_verify_top_k: int = 0  # post-route-verify the top K candidates (+ baseline) after optimize; 0 = off
    raw: dict = field(default_factory=dict)


def _read_json(p: Path) -> dict:
    return json.loads(p.read_text()) if p.exists() else {}


def load_task(task_dir: str | Path) -> TaskContext:
    task_dir = Path(task_dir).resolve()
    if not task_dir.is_dir():
        raise FileNotFoundError(f"task dir not found: {task_dir}")

    spec = _read_json(task_dir / "spec.json")
    constraints = _read_json(task_dir / "constraints.json")
    budget = _read_json(task_dir / "budget.json")
    if not spec:
        raise ValueError(f"missing or empty spec.json in {task_dir}")

    src_files = [task_dir / f for f in spec.get("entry_files", [])]
    tb_files = [task_dir / f for f in spec.get("testbench_files", [])]

    missing = [str(p) for p in src_files + tb_files if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"task {spec.get('task_id', task_dir.name)} missing files: {missing}"
        )

    src_dir = src_files[0].parent if src_files else task_dir / "src"
    tb_dir = tb_files[0].parent if tb_files else task_dir / "tb"
    target = constraints.get("target", {})

    # Optional lexicographic optimization order. Deliberately tolerant: an
    # absent or unrecognized value falls back to the default
    # "satisfice_then_area" rather than raising.
    #
    # Valid enum: speed_first | area_first | adp | satisfice_then_area |
    # pareto_report. Legacy aliases are folded in for migration (never raise):
    #   "throughput" -> "speed_first"
    #   "latency"    -> "speed_first"  (there is no latency-first mode in the
    #                    new enum; latency is now a tiebreak under speed_first,
    #                    so legacy latency tasks map to speed_first)
    VALID = ("speed_first", "area_first", "adp", "satisfice_then_area", "pareto_report")
    ALIASES = {"throughput": "speed_first", "latency": "speed_first"}
    objective = str(spec.get("objective", "satisfice_then_area")).strip().lower()
    objective = ALIASES.get(objective, objective)
    if objective not in VALID:
        objective = "satisfice_then_area"

    # Optional extra include dirs (headers the kernel needs but the agent never
    # edits — e.g. a vendored ap_int.h). HOST-CSIM ONLY: the gpp backend adds
    # them so real HLS code compiles without Vitis; the vitis backend must NOT
    # (the open-source AP-types headers #error under csynth — the tool ships
    # its own). Task-relative paths resolve against the task dir; absolute
    # paths pass through. Tolerant: absent -> []; a missing dir is NOT an error
    # here (it surfaces as a compile failure with a clear -I path in the log,
    # which is more actionable than a load-time raise).
    include_dirs = [(task_dir / d).resolve() for d in spec.get("include_dirs", [])]

    # Optional explicit interval_max ceiling for satisfice_then_area. Tolerant:
    # non-numeric or absent -> None (no explicit target).
    throughput_target = None
    tgt_raw = spec.get("throughput_target")
    if tgt_raw is not None:
        try:
            throughput_target = float(tgt_raw)
        except (TypeError, ValueError):
            throughput_target = None

    # Optional post-route verification depth: after the optimize loop, run
    # Vivado implementation on the top K candidates (+ the baseline) and pick
    # the winner from measured PPA. Lives under constraints.target with the
    # other tool/part knobs. Tolerant: absent/non-numeric/negative -> 0 (off).
    impl_verify_top_k = 0
    try:
        impl_verify_top_k = max(0, int(target.get("impl_verify_top_k", 0)))
    except (TypeError, ValueError):
        impl_verify_top_k = 0

    return TaskContext(
        task_id=spec.get("task_id", task_dir.name),
        task_dir=task_dir,
        top_function=spec.get("top_function", ""),
        language=spec.get("language", "cpp"),
        src_files=src_files,
        tb_files=tb_files,
        src_dir=src_dir,
        tb_dir=tb_dir,
        clock_period_ns=float(target.get("clock_period_ns", 10.0)),
        fpga_part=target.get("fpga_part", ""),
        policy=spec.get("policy", {}),
        budget=budget,
        objective=objective,
        throughput_target=throughput_target,
        include_dirs=include_dirs,
        impl_verify_top_k=impl_verify_top_k,
        raw={"spec": spec, "constraints": constraints, "budget": budget},
    )
