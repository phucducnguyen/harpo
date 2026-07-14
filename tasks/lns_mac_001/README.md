# lns_mac_001 — real-artifact case study: LNS log8 MAC

Unlike the constructed tasks in this suite, this bundle snapshots a **real
research artifact**: the Logarithmic Number System (log8) Multiply-Accumulate
unit from the author's 2024 MS project (EE297B, San José State University),
as later repaired in a 2026 review pass.

- **Source of truth:** https://github.com/phucducnguyen/lns-log8-mac
  (local clone `~/projects/LNS_Madam`), snapshot at commit `9c977d3`
  (2026-07-11, clean tree). This bundle is a fixture — fixes belong upstream,
  then re-snapshot.
- **Why it exists:** experimental setup for the follow-up case-study paper.
  The code as archived with the 2024 report had real numerical bugs (unsigned
  exponent wrapping values < 1.0, zero encoded as +1.0, accumulator overflow,
  never-zeroed partial sums); they were fixed post-report, which means the
  report's synthesis figures no longer describe the working datapath. This
  task regenerates honest post-fix PPA and lets the agent hunt pragma headroom
  on the fixed design, with HARPO's replayable evidence trail.

## Layout notes (vs. the upstream repo)

- Upstream `src/add/`, `src/mul/` are **flattened** into `src/` here (candidate
  forks copy sources flat by basename). The only edits vs. upstream are the
  mechanical `#include` path rewrites that flattening forces; everything else
  is byte-identical.
- Testbench = upstream `test_bench/mac_tb.cpp` (asserted, deterministic seeds,
  double-precision golden model over quantized inputs; tolerance
  `5%|golden| + 1% sum|products| + 2^-8`). The agent may never edit it.
  **Coverage scope:** the tb drives `mac_array` (the arithmetic core the
  matrix wrapper loops over), not the synthesized top `mac_nxn_array` itself
  — so a functional edit confined to the wrapper's loop nest would compile
  as dead code under gpp csim. Fine for pragma-only edits (g++ ignores
  pragmas; the accepted run-1 candidate diffs from baseline by pragma lines
  only), but a future functional-repair run on this task should extend the
  tb to also call the top wrapper.
- `ap_int.h` comes from the repo-level vendored dep via the spec's
  `include_dirs` key (`.deps/hls_types/include`, gitignored). Fetch once:

  ```bash
  git clone --depth 1 https://github.com/Xilinx/HLS_arbitrary_Precision_Types.git .deps/hls_types
  ```

  (Apache-2.0. Host-csim only: the vitis backend deliberately ignores
  `include_dirs` — these open-source headers `#error` under csynth, and the
  tool ships its own synthesizable ap_int.h.)

## Task design choices

- **Top = `mac_nxn_array`** — matches upstream `mac/hls_config.cfg`, i.e. the
  design as the project itself synthesizes it. The testbench exercises the
  `mac_array` datapath it wraps.
- **Part = xc7z020clg400-1 @ 10 ns** — HARPO's verified free-tier toolchain.
  The 2024 report swept Artix/Kintex/Virtex; reproducing that sweep is
  a planned follow-up (clone this task, change `constraints.json` per family).
  Upstream's cfg targets xczu9eg; PPA numbers here are NOT comparable to the
  report's tables until the family sweep runs.
- **No `throughput_target`** — deliberately absent so the zero-token recipe
  probe derives one (the paper's Fix 3), exercised here on a real artifact.
- **Objective `satisfice_then_area`** — the LNS design's entire premise is
  area/power efficiency, so satisfice-throughput-then-minimize-area is the
  honest objective, and exactly the over-parallelization guard the paper
  argues for.
