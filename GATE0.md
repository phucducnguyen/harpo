# Gate 0 — prove the toolchain — ✅ PASSED (2026-06-14, atlas)

Both gates pass on **atlas** with **Vitis HLS 2025.2** (free on Linux, pre-2026.1).

- **Gate 0a — csim (functional): just a C++ compiler.** Vitis HLS csim is
  "compile the C++ + run the testbench", and g++ ignores `#pragma HLS`, so
  `python3 -m harpo run <task> --stage csim` reproduces csim pass/fail with
  **no Vitis** (g++ 13.3.0 on atlas). ✅
- **Gate 0b — csynth / PPA: real Vitis HLS 2025.2.** Full flow runs end-to-end;
  `python3 -m harpo run <task> --stage csynth --backend vitis_hls` produces
  parsed latency / II / resources. ✅

## Verified config (the runner's "hardcoded-nothing" inputs)

- **Tool:** Vitis HLS v2025.2 (SW Build 6295257, Nov 14 2025)
- **Install:** `~/tools/Xilinx/2025.2` (user-owned, no sudo). Env:
  `source ~/tools/Xilinx/2025.2/Vitis/settings64.sh`
- **Part:** `xc7z020clg400-1` (PYNQ-Z2, free-tier covered) · **Clock:** 10.0 ns
- **vadd_001 result:** csim `TEST PASSED`; csynth II=1, depth=17,
  Est. Fmax 136.99 MHz (est. clock 7.300 ns), LUT 2939 (5%), FF 2879 (2%),
  BRAM 4 (1%), DSP 0.
- **Reports:** `hls_proj/sol1/syn/report/csynth.xml` (overall, has util%) and
  `<top>_csynth.xml` (per-module). csim: `sol1/csim/report/<top>_csim.log`.

## ⚠️ Install gotcha — recreate the `vitis_hls` launcher

The unified 2025.2 web installer (GUI) ships the `vitis_hls` **binary**
(`Vitis/bin/unwrapped/lnx64.o/vitis_hls`) and libs but **omits the thin
`bin/vitis_hls` launcher** — `bin/` only has the new Electron `vitis` IDE. Without
the launcher, `vitis_hls` is not on PATH even after sourcing settings64.sh.

**Fix (already applied; re-apply on any reinstall):** create
`~/tools/Xilinx/2025.2/Vitis/bin/vitis_hls` as the standard loader wrapper
(same pattern as `Vivado/bin/vivado`):

```bash
#!/bin/bash
. "`dirname \"$0\"`/setupEnv.sh"
XILINX_HLS=`dirname "$RDI_BINROOT"`; export XILINX_HLS
export RDI_DEPENDENCY="XILINX_VIVADO_HLS:XILINX_HLS"
export _RDI_NEEDS_PYTHON=True RDI_USE_JDK21=True
RDI_PROG=`basename "$0"`
"$RDI_BINROOT"/loader -exec $RDI_PROG "$@"
```

then `chmod +x` it. Verify: `vitis_hls -version`.

## Licensing reality

Since **Vitis 2026.1 (2026-05-25), the free "Basic" tier is WINDOWS-ONLY**;
Linux 2026.1+ needs a paid "Core" tier (~$1,200-1,800/yr). **Pre-2026.1
(≤2025.2) is still free on Linux** — which is why we run 2025.2 on atlas.
**Never install 2026.1+ on Linux.** xc7z020 is entry-level / free-tier covered.

## Manual repro (no Python)

```bash
source ~/tools/Xilinx/2025.2/Vitis/settings64.sh
cd ~/projects/harpo/tasks/vadd_001/scripts
vitis_hls -f run_hls.tcl        # part/clock via LS_PART / LS_PERIOD env
```
