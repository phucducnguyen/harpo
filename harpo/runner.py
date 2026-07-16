"""Tool Runner: pluggable backends that execute a stage and return raw output.

Backends
--------
gpp        : host C++ compile + run = functional csim equivalent. Vitis HLS
             csim is itself just "compile the C++ and run the testbench", and
             g++ silently ignores `#pragma HLS ...`, so this reproduces csim
             pass/fail WITHOUT Vitis installed. Cannot do csynth/cosim/PPA and
             does NOT catch non-synthesizable constructs (recursion, malloc,
             unsupported STL) — those only surface under real csynth.
vitis_hls  : (later) real Vitis HLS flow via run_hls.tcl — csim/csynth/cosim.

The agent always talks to run_stage(); swapping g++ for vitis_hls later is a
backend change, not an agent change.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from .task import TaskContext

CXX_CANDIDATES = ["g++", "clang++", "c++"]
SRC_EXTS = (".cpp", ".cc", ".cxx", ".c")
RUN_TIMEOUT_SEC = 30


def _find_cxx() -> str | None:
    env = os.environ.get("CXX")
    if env and shutil.which(env):
        return env
    for c in CXX_CANDIDATES:
        if shutil.which(c):
            return c
    return None


def run_csim_gpp(task: TaskContext, out_dir: Path) -> dict:
    """Compile kernel + testbench with a host C++ compiler and run it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "stage": "csim",
        "backend": "gpp",
        "available": False,
        "compiler": None,
        "compile_rc": None,
        "compile_log": "",
        "run_rc": None,
        "run_stdout": "",
        "run_stderr": "",
        "duration_sec": 0.0,
    }
    t0 = time.time()

    cxx = _find_cxx()
    if cxx is None:
        result["compile_log"] = (
            "no C++ compiler found (looked for $CXX, g++, clang++, c++). "
            "Install one to enable csim, e.g.  sudo apt install -y g++"
        )
        result["duration_sec"] = round(time.time() - t0, 3)
        return result

    result["available"] = True
    result["compiler"] = cxx

    binary = out_dir / "csim.bin"
    sources = [
        str(p) for p in (task.src_files + task.tb_files)
        if p.suffix.lower() in SRC_EXTS
    ]
    extra_incs = [f"-I{d}" for d in task.include_dirs]
    cmd = [
        cxx, "-O0", "-std=c++14",
        *sources,
        f"-I{task.src_dir}", f"-I{task.tb_dir}", *extra_incs,
        "-o", str(binary),
    ]
    comp = subprocess.run(cmd, capture_output=True, text=True)
    result["compile_rc"] = comp.returncode
    result["compile_log"] = (comp.stderr + comp.stdout).strip()

    if comp.returncode == 0:
        try:
            run = subprocess.run(
                [str(binary)], capture_output=True, text=True,
                timeout=RUN_TIMEOUT_SEC,
            )
            result["run_rc"] = run.returncode
            result["run_stdout"] = run.stdout.strip()
            result["run_stderr"] = run.stderr.strip()
        except subprocess.TimeoutExpired:
            result["run_rc"] = -1
            result["run_stderr"] = (
                f"run timed out after {RUN_TIMEOUT_SEC}s (possible infinite loop)"
            )

    result["duration_sec"] = round(time.time() - t0, 3)
    return result


VITIS_TIMEOUT_SEC = 900


def _vitis_hls_exe() -> str | None:
    env = os.environ.get("VITIS_HLS")
    if env and shutil.which(env):
        return env
    return shutil.which("vitis_hls")


def _gen_tcl(task: TaskContext, proj_name: str) -> str:
    """Emit a self-contained run.tcl pointed at this task/candidate's sources.

    Part/clock are task-injected (never hardcoded into the agent); the source
    list comes straight from the candidate view, so the same path works for the
    base task and any forked candidate's edited copy.
    """
    # Put the (candidate) source dir AND tb dir on the compiler include path so
    # `#include "kernel.h"` resolves to the candidate's edited header, not a
    # stray copy — mirrors the gpp backend's -I flags and keeps isolation honest.
    # Task include_dirs are deliberately NOT passed here: they vendor headers
    # the real tool ships natively (ap_int.h & friends), and the open-source
    # AP-types headers hard-#error under csynth ("does not support synthesis").
    cflags = f'-I{task.src_dir} -I{task.tb_dir}'
    add_src = "\n".join(f'add_files {{{p}}} -cflags "{cflags}"' for p in task.src_files)
    add_tb = "\n".join(f'add_files -tb {{{p}}} -cflags "{cflags}"' for p in task.tb_files)
    return f"""\
open_project -reset {proj_name}
set_top {task.top_function}
{add_src}
{add_tb}
open_solution -reset "sol1"
set_part {{{task.fpga_part}}}
create_clock -period {task.clock_period_ns} -name default
csim_design
csynth_design
exit
"""


def run_csynth_vitis(task: TaskContext, out_dir: Path) -> dict:
    """Real Vitis HLS flow: csim + csynth via a generated run.tcl.

    Returns raw output plus the located csynth XML/RPT report contents and the
    csim log, for parse_csynth() to normalize. Requires `vitis_hls` on PATH
    (source <install>/Vitis/2025.2/settings64.sh first) or $VITIS_HLS set.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "stage": "csynth",
        "backend": "vitis_hls",
        "available": False,
        "tool": None,
        "rc": None,
        "log": "",
        "csynth_xml": None,
        "csynth_xml_module": None,
        "csynth_rpt": None,
        "csynth_report_path": None,
        "csim_log": None,
        "duration_sec": 0.0,
    }
    t0 = time.time()

    exe = _vitis_hls_exe()
    if exe is None:
        result["log"] = (
            "vitis_hls not found. Source the Vitis env first, e.g.\n"
            "  source ~/tools/Xilinx/2025.2/Vitis/settings64.sh\n"
            "or set $VITIS_HLS to the launcher path."
        )
        result["duration_sec"] = round(time.time() - t0, 3)
        return result

    result["available"] = True
    result["tool"] = exe

    proj = "hls_proj"
    tcl_path = out_dir / "run_harpo.tcl"
    tcl_path.write_text(_gen_tcl(task, proj))

    try:
        run = subprocess.run(
            [exe, "-f", str(tcl_path)],
            cwd=str(out_dir), capture_output=True, text=True,
            timeout=VITIS_TIMEOUT_SEC,
        )
        result["rc"] = run.returncode
        result["log"] = (run.stdout + run.stderr).strip()
    except subprocess.TimeoutExpired:
        result["rc"] = -1
        result["log"] = f"vitis_hls timed out after {VITIS_TIMEOUT_SEC}s"
        result["duration_sec"] = round(time.time() - t0, 3)
        return result

    top = task.top_function
    syn_report_dir = out_dir / proj / "sol1" / "syn" / "report"
    # Prefer the overall report (csynth.xml) — it carries the nested AVAIL_/UTIL_
    # area block used for resource-overuse checks. The per-module
    # <top>_csynth.xml lacks that nested block (raw counts + a top-level
    # AvailableResources only). We keep the overall report as primary, but ALSO
    # stash the per-module report as csynth_xml_module so parse_csynth can merge
    # AVAIL/UTIL from whichever report actually carries them if the primary is
    # missing them (the parser computes util% from count/avail either way).
    overall_xml = syn_report_dir / "csynth.xml"
    module_xml = syn_report_dir / f"{top}_csynth.xml"
    for cand_xml in (overall_xml, module_xml):
        if cand_xml.exists():
            result["csynth_xml"] = cand_xml.read_text()
            result["csynth_report_path"] = str(cand_xml)
            break
    # Secondary report (the one we didn't pick as primary), for merge fallback.
    primary_path = result["csynth_report_path"]
    for cand_xml in (overall_xml, module_xml):
        if cand_xml.exists() and str(cand_xml) != primary_path:
            result["csynth_xml_module"] = cand_xml.read_text()
            break
    for cand_rpt in (syn_report_dir / f"{top}_csynth.rpt", syn_report_dir / "csynth.rpt"):
        if cand_rpt.exists():
            result["csynth_rpt"] = cand_rpt.read_text()
            result["csynth_report_path"] = result["csynth_report_path"] or str(cand_rpt)
            break

    csim_log = out_dir / proj / "sol1" / "csim" / "report" / f"{top}_csim.log"
    if csim_log.exists():
        result["csim_log"] = csim_log.read_text()

    result["duration_sec"] = round(time.time() - t0, 3)
    return result


# Post-route implementation is minutes-long (measured ~4.6 min on the LNS MAC:
# Vivado synth ~2 min + place/route ~1 min inside export_design), so it gets a
# far larger ceiling than csynth.
IMPL_TIMEOUT_SEC = 1800


def _gen_impl_tcl(task: TaskContext, proj_name: str) -> str:
    """Emit a run.tcl that carries a candidate through csynth AND Vivado
    post-route implementation via `export_design -flow impl`.

    Same source/part/clock injection as _gen_tcl, with two deliberate
    differences: csim_design is skipped (correctness is already gated by the
    loop's csim stage before an impl run is ever allowed) and cosim is not run
    (this rung measures PPA, not function). export_design internally drives
    Vivado synth + place & route and writes the measured report to
    <proj>/sol1/impl/report/verilog/export_impl.xml. Task include_dirs stay
    excluded for the same reason as _gen_tcl (host-csim-only vendored headers).
    """
    cflags = f'-I{task.src_dir} -I{task.tb_dir}'
    add_src = "\n".join(f'add_files {{{p}}} -cflags "{cflags}"' for p in task.src_files)
    return f"""\
open_project -reset {proj_name}
set_top {task.top_function}
{add_src}
open_solution -reset "sol1"
set_part {{{task.fpga_part}}}
create_clock -period {task.clock_period_ns} -name default
csynth_design
export_design -flow impl -rtl verilog -format ip_catalog
exit
"""


def run_impl_vitis(task: TaskContext, out_dir: Path) -> dict:
    """Measured post-route PPA: csynth + Vivado impl via export_design.

    Runs inside the same vitis_hls executable as run_csynth_vitis (HLS drives
    Vivado internally), so no separate Vivado discovery is needed. Returns the
    export_impl.xml contents for parse_impl() to normalize.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "stage": "impl",
        "backend": "vitis_hls",
        "available": False,
        "tool": None,
        "rc": None,
        "log": "",
        "impl_xml": None,
        "impl_report_path": None,
        "duration_sec": 0.0,
    }
    t0 = time.time()

    exe = _vitis_hls_exe()
    if exe is None:
        result["log"] = (
            "vitis_hls not found. Source the Vitis env first, e.g.\n"
            "  source ~/tools/Xilinx/2025.2/Vitis/settings64.sh\n"
            "or set $VITIS_HLS to the launcher path."
        )
        result["duration_sec"] = round(time.time() - t0, 3)
        return result

    result["available"] = True
    result["tool"] = exe

    proj = "impl_proj"
    tcl_path = out_dir / "run_harpo_impl.tcl"
    tcl_path.write_text(_gen_impl_tcl(task, proj))

    try:
        run = subprocess.run(
            [exe, "-f", str(tcl_path)],
            cwd=str(out_dir), capture_output=True, text=True,
            timeout=IMPL_TIMEOUT_SEC,
        )
        result["rc"] = run.returncode
        result["log"] = (run.stdout + run.stderr).strip()
    except subprocess.TimeoutExpired:
        result["rc"] = -1
        result["log"] = f"vitis_hls impl timed out after {IMPL_TIMEOUT_SEC}s"
        result["duration_sec"] = round(time.time() - t0, 3)
        return result

    impl_xml = out_dir / proj / "sol1" / "impl" / "report" / "verilog" / "export_impl.xml"
    if impl_xml.exists():
        result["impl_xml"] = impl_xml.read_text()
        result["impl_report_path"] = str(impl_xml)

    result["duration_sec"] = round(time.time() - t0, 3)
    return result


BACKENDS = {
    ("csim", "gpp"): run_csim_gpp,
    ("csynth", "vitis_hls"): run_csynth_vitis,
    ("impl", "vitis_hls"): run_impl_vitis,
}


def run_stage(task: TaskContext, stage: str, out_dir: Path,
              backend: str = "gpp") -> dict:
    fn = BACKENDS.get((stage, backend))
    if fn is None:
        raise NotImplementedError(
            f"no backend for stage={stage} backend={backend} "
            f"(available: {sorted(BACKENDS)})"
        )
    return fn(task, out_dir)
