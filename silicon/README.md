# silicon/ — from csynth estimates to measured silicon

HARPO's loop stops at the csynth report by design: its numbers are Vitis HLS
*estimates*. This workspace carries the case-study winner — the HARPO-fixed
`lns_mac_001` (see `../docs/case-study/`) — through the stages after the
agent's job ends:

| Stage | Tool | Question it answers |
|---|---|---|
| C/RTL co-simulation | Vitis HLS + xsim | Does the generated RTL still match the C golden model? |
| Place & route (OOC) | Vivado via `export_design -flow impl` | What are the **real** post-route LUT/FF/DSP counts and achieved clock? |
| Board run | PYNQ-Z2 overlay | Does it work on actual silicon, and how fast wall-clock? |

Nothing in `../tasks/` or `../docs/` is modified; task sources are referenced
in place. The one exception is `src/mac_silicon.cpp`: the committed case-study
winner with a single disclosed deviation — block control `ap_ctrl_none` →
`s_axilite` — because cosim cannot drive a non-II=1 `ap_ctrl_none` top
(COSIM 212-345) and the PYNQ overlay needs AXI-Lite control regardless.
Datapath, loop structure, and the winning pragma fix are unchanged.

## Files

- `src/mac_silicon.cpp` — the case-study winner, control protocol only
  changed (see above; full rationale in the file header).
- `run_silicon.tcl` — csim → csynth → cosim → `export_design -flow impl`
  on `xc7z020clg400-1` @ 10 ns (the PYNQ-Z2 part, same target as the paper).
- `tb/mac_nxn_cosim_tb.cpp` — cosim testbench driving the synthesis TOP
  (`mac_nxn_array`) directly. The task testbench exercises the `mac_array`
  subfunction, which cosim cannot replay; this one reuses the identical
  golden model and tolerance (`5%|golden| + 1% sum|products| + 2^-8`,
  saturation-clamped, deterministic seeds) on directed + random 8×8 matrices.
  The 10k-trial statistical gate stays in csim where it belongs — cosim's job
  is RTL equivalence and protocol correctness, not re-deriving error stats.

## Running

```bash
source <Xilinx>/2025.2/Vitis/settings64.sh
cd silicon && vitis_hls -f run_silicon.tcl
```

Post-route results: `proj_lns_silicon/sol_pynqz2/impl/report/verilog/export_impl.rpt`
(compare against the csynth estimates in `../docs/ablations/canonical/TABLE.md`).

Project directories (`proj_*/`) and logs are build output — not committed.

## Results — 2026-07-15 run (Vitis HLS / Vivado 2025.2, xc7z020clg400-1 @ 10 ns)

C/RTL co-simulation: **PASS** (Verilog, xsim) — all directed + random 8×8
matrices within the golden-model tolerance. Latency 2,979 cycles per matmul
(min = avg = max; fully deterministic), initiation interval 2,993 cycles →
**29.8 µs per 8×8 matmul** at 100 MHz, m_axi transfers included.

Vivado out-of-context place & route (`export_impl.rpt`):

| Metric | csynth estimate | **Measured post-route** |
|---|---|---|
| LUT | 21,013 (39.5%) | **8,596 (16.2%)** |
| FF | 8,033 | **8,675** |
| DSP | 0 | **0** |
| BRAM_18K | 4 | **2** |
| Timing @ 10 ns | est. Fmax 101 MHz | **met — worst path 9.362 ns (≈106.8 MHz)** |

Two honest observations: (1) csynth's LUT estimate was ~2.4× pessimistic —
the HARPO-fixed design measures 16.2%, not 39.5%; estimate-vs-measured gaps
cut both ways and this is exactly why this workspace exists. (2) The inner
pipeline's II=1 target is NOT met — achieved II is 16 (m_axi port contention:
one gmem bundle serves 2×8 reads per iteration). The cosim interval confirms
real throughput, and timing still closes post-route. An II-improvement pass
(separate bundles / local buffering) is future work, deliberately out of
scope for reproducing the case-study artifact.

## Board kit — PYNQ-Z2 overlay (built 2026-07-15, awaiting board run)

- `overlay/` — `build_overlay.tcl` (rerunnable Vivado batch build: PS7 + IP +
  AXI automation @ 100 MHz FCLK0) and its outputs `mac_lns.bit` + `mac_lns.hwh`.
  Full-overlay P&R: **timing MET (WNS +0.514 ns)**, 9,097 LUT (17.1%),
  9,174 FF, 1 BRAM tile, **0 DSP** — the LNS point: log-domain MAC maps to
  LUT fabric, no DSP48s. IP at AXI-Lite `0x4000_0000`, gmem via S_AXI_HP0.
- `host/` — `gen_vectors.cpp` + `build_and_run.sh`: replays the cosim
  testbench's exact matrices through the C model and dumps raw 5-byte-element
  binaries (DDR layout = natural host struct layout, verified against the
  RTL's WSTRB pattern and a host `sizeof` probe).
- `board/` — copy this whole directory plus the two `overlay/mac_lns.*` files
  to the board (see `board/README.md`); `run_mac_lns.ipynb` runs all 10
  vector cases (byte-exact compare) and a 1000-launch timing loop.

## Piece B — hand-written RTL vs HLS (2026-07-15, `rtl/`)

`rtl/` is a hand-written SystemVerilog implementation of the same 8×8 LNS
matmul, Cocotb-verified **bit-exact** against the same C golden model
(10/10 committed vectors byte-exact + element-level and random suites;
`make -C rtl/tb`), then measured through the same Vivado OOC place & route
(`rtl/impl/run_impl.tcl`). Three-row measured picture on xc7z020 @ 10 ns:

| Design | LUT (util) | FF | DSP | cycles/matmul | timing |
|---|---|---|---|---|---|
| Archived 2024 HLS | est. 89,773 (168.7%) | — | — | — | **does not fit** |
| HARPO-fixed HLS (kernel) | **8,596 (16.2%)** | 8,675 | 0 | 2,979 (II=16) | met (9.362 ns) |
| Hand RTL (datapath) | **4,271 (8.0%)** | 3,477 | 0 | **75 (II=1)** | met (WNS +1.733) |

**Read the caveat before quoting:** the rows are not kernel-equivalent. The
HLS numbers include its s_axilite + m_axi adapters and DDR transfers; the
hand RTL is datapath-only (operands assumed on-chip, wide parallel ports).
What the comparison fairly shows: the HLS kernel's II=16 was m_axi port
serialization, not arithmetic — the same datapath sustains II=1 by hand —
and both sides map LNS MAC to pure LUT fabric (0 DSP, forced `use_dsp="no"`
in the RTL to match the HLS `impl=fabric` intent). Full details, interface
spec, and replication steps: `rtl/README.md`.

## Honest-scope notes

- The archived 2024 design is not run through place & route here: at 168.7%
  LUT utilization it cannot place on the xc7z020 at all — "does not fit" *is*
  its post-route result on this part.
- `ap_ctrl_none` tops are not always co-simulatable; if the tool refuses,
  the script still completes the place & route leg and says so
  (`SILICON_RUN_DONE cosim_ok=0`). Any control-protocol variant used to
  unblock cosim or the board overlay changes the block-level handshake only,
  never the datapath, and must be disclosed next to the numbers it produced.
