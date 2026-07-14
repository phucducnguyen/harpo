#!/usr/bin/env python3
"""FPGA family sweep for the lns_mac_001 case study — baseline vs LLM-fixed.

Synthesizes BOTH variants of the LNS MAC on several parts and writes one
summary JSON, so the case-study paper's cross-family table is regenerable
from committed artifacts:

  * baseline — tasks/lns_mac_001/src verbatim (the archived 2024 design,
    2026 numerics fixes, original top-level PIPELINE pragma)
  * fixed    — same sources with mac.cpp replaced by the accepted candidate
    from the first LLM run (docs/case-study/lns_mac_001_ollama_run1_winner.mac.cpp)

Requires vitis_hls on PATH (source the Vitis settings64.sh first).
Parts default to: the case-study anchor (xc7z020), the upstream repo's own
MAC target (xczu9eg), and a Virtex-7 representative. Parts whose device
family isn't installed FAIL LOUDLY into the summary — no silent skips.
This Vitis 2025.2 install carries ONLY the Zynq families (`list_part` ->
zynq/zynquplus/RFSoC): the Virtex-7 attempt is kept in the sweep precisely
so the summary records "Part not installed" as evidence. The 2024 report's
Artix/Kintex/Virtex sweep therefore needs device support added to the
install first — noted in docs/case-study/README.md.

Run:  python3 scripts/family_sweep.py
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harpo.parser import parse_csynth  # noqa: E402
from harpo.runner import run_stage  # noqa: E402
from harpo.task import load_task  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TASK_DIR = ROOT / "tasks" / "lns_mac_001"
WINNER_MAC = ROOT / "docs" / "case-study" / "lns_mac_001_ollama_run1_winner.mac.cpp"
OUT_JSON = ROOT / "docs" / "case-study" / "lns_mac_001_family_sweep.json"
SWEEP_RUNS = ROOT / "runs" / "lns_mac_001_sweep"

PARTS = [
    ("zynq7000", "xc7z020clg400-1"),           # case-study anchor (PYNQ-Z2 class)
    ("zynquplus", "xczu9eg-ffvb1156-2-e"),     # upstream repo's own MAC target
    ("artix7", "xc7a200tfbv484-2"),            # upstream repo's own multiplier target
    ("kintex7", "xc7k325tffg900-2"),           # Kintex representative (KC705 part)
    ("virtex7", "xc7vx485tffg1761-2"),         # Virtex representative (VC707 part)
]

# Independent Vitis instances run concurrently (separate workdirs); each is
# mostly single-threaded at ~1.5-2.5 GB, so cap modestly rather than by nproc.
MAX_WORKERS = 4

VARIANTS = ("baseline", "fixed")

KEEP = ("part", "clock_estimated_ns", "fmax_mhz", "latency_worst",
        "interval_max", "lut", "ff", "dsp", "bram_18k",
        "avail_lut", "util_lut", "util_ff", "util_bram")


def make_variant_src(variant: str, dest: Path, base_task) -> list[Path]:
    """Copy the task sources flat into ``dest``; overlay the winner mac.cpp."""
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for f in base_task.src_files:
        tgt = dest / Path(f).name
        shutil.copy2(f, tgt)
        files.append(tgt)
    if variant == "fixed":
        shutil.copy2(WINNER_MAC, dest / "mac.cpp")
    return files


def run_one(base, variant: str, src_dir: Path, src_files: list[Path],
            family: str, part: str) -> dict:
    out_dir = SWEEP_RUNS / variant / family
    view = dataclasses.replace(
        base, fpga_part=part, src_dir=src_dir, src_files=src_files)
    print(f"[sweep] {variant} on {part} ...", flush=True)
    raw = run_stage(view, "csynth", out_dir, backend="vitis_hls")
    parsed = parse_csynth(raw)
    row = {
        "variant": variant,
        "family": family,
        "requested_part": part,
        "status": parsed["status"],
        "pass": parsed["pass"],
        "violations": parsed["violations"],
        "errors": parsed["errors"][:3],
        "metrics": {k: (parsed["metrics"] or {}).get(k) for k in KEEP},
    }
    print(f"[sweep] {variant} on {part} -> {row['status']}  "
          f"lut={row['metrics'].get('lut')} "
          f"util_lut={row['metrics'].get('util_lut')} "
          f"lat={row['metrics'].get('latency_worst')}", flush=True)
    return row


def main() -> int:
    base = load_task(TASK_DIR)
    jobs = []
    for variant in VARIANTS:
        src_dir = SWEEP_RUNS / variant / "src"
        src_files = make_variant_src(variant, src_dir, base)
        for family, part in PARTS:
            jobs.append((variant, src_dir, src_files, family, part))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(run_one, base, *j) for j in jobs]
        results = [f.result() for f in futures]  # preserves job order

    # Deterministic output order regardless of completion order.
    order = {(v, p): i for i, (v, _s, _f, _fam, p) in enumerate(jobs)}
    results.sort(key=lambda r: order[(r["variant"], r["requested_part"])])

    summary = {
        "task": "lns_mac_001",
        "clock_period_ns": base.clock_period_ns,
        "top_function": base.top_function,
        "variants": {
            "baseline": "tasks/lns_mac_001/src (archived design, top-level PIPELINE)",
            "fixed": "mac.cpp from docs/case-study/lns_mac_001_ollama_run1_winner.mac.cpp",
        },
        "note": ("Artix-7/Kintex-7 absent: device families not installed in "
                 "this Vitis 2025.2 setup, NOT a design limitation."),
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"[sweep] wrote {OUT_JSON.relative_to(ROOT)}")
    failures = [r for r in results if r["status"] in
                ("tool_unavailable", "synthesis_fail", "report_missing")]
    if failures:
        print(f"[sweep] {len(failures)} run(s) did not synthesize — recorded, "
              "see errors in the summary JSON")
    return 0


if __name__ == "__main__":
    sys.exit(main())
