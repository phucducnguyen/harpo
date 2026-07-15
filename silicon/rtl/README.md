# rtl/ — hand-written LNS 8×8 matmul (the "Piece B" of the HLS-vs-RTL study)

The `silicon/` workspace carried the HARPO-fixed HLS kernel from a csynth
estimate through Vivado place & route. This directory is the other half of the
comparison: the **same LNS 8×8 matrix multiply written by hand in SystemVerilog**,
verified bit-exact against the same C golden model, and pushed through the same
out-of-context P&R on the same part. The point is not "RTL beats HLS" in the
abstract — it is to see, on one concrete kernel, exactly what the HLS memory/AXI
scaffolding costs and what a datapath-only hand implementation looks like next
to it. The honest asymmetries are spelled out below; read them before quoting
any single number.

The C reference is authoritative. Every module here reproduces
`tasks/lns_mac_001/src/{LNS_datatype,mul_unit,add_unit}` and
`silicon/src/mac_silicon.cpp` **bit-for-bit** — same outputs for same inputs,
including saturation, underflow-to-zero, and the Mitchell-approximation edge
cases. Where the C looks odd it is copied anyway and flagged; this is a fidelity
exercise, not a redesign.

## Format (recap)

16-bit element, `{sign, zero, exponent[6:0], quotient[3:0], remainder[2:0]}`,
value `±2^(exponent/8)` with `exponent = quotient*8 + remainder` (floored
division, `remainder ≥ 0`). B=7, Q=4, R=3, Γ=8; `EXP_MIN=-64`, `EXP_MAX=63`.

## Files

### `src/` — the design (SV-2012, hand-written)
- `lns_pkg.sv` — element record + the datapath as pure combinational functions.
  These functions are the single source of truth: the combinational reference
  modules and the pipeline both call them, so they cannot drift.
- `lns_mul.sv` — combinational LNS multiply (sign XOR, exponent add, saturate).
- `lns_add8.sv` — combinational 8-way log-domain adder (the interesting block):
  bucket by (sign × remainder), accumulate `2^(quotient+8)`, Mitchell `2^(r/8)`
  scale, positive-minus-negative reduce, convert the fixed-point sum back to LNS.
- `lns_mac8.sv` — one dot product = 8 multiplies + `add8`, **pipelined to II=1**
  (10 stages; latency is free at II=1, so the long bucket-build / reduce /
  convert-back poles are split until each closes 10 ns). `use_dsp="no"`.
- `lns_matmul_8x8.sv` — top. One `lns_mac8` is time-shared across the 64 output
  positions, one issue per clock.

### `tb/` — the cocotb bench (golden model via ctypes, LNS never re-implemented)
- `lns_golden.py` — loads `libgolden.so` (the exact synthesized C, compiled
  `-shared`) and converts between the C 5-byte element layout and the 16-bit RTL
  word.
- `test_mul.py`, `test_add8.py`, `test_matmul.py` — the three suites.
- `Makefile`, `sim.mk` — `make` builds the golden lib and runs all three.

### `impl/` — measurement
- `run_impl.tcl` + `clk.xdc` — OOC synth + place & route on `xc7z020clg400-1`
  @ 10 ns, post-route utilization + timing to `reports/`.

## Top-level interface

Simple synchronous, **no AXI, no memory ports** (deliberate — see caveats):

| Port | Dir | Meaning |
|---|---|---|
| `clk`, `rst_n` | in | clock, active-low async reset |
| `start` | in | 1-cycle pulse: latch operands and begin |
| `a_flat[1023:0]` | in | A row-major; `A[i][k]` at `a_flat[(i*8+k)*16 +: 16]` |
| `b_flat[1023:0]` | in | B row-major; `B[k][j]` at `b_flat[(k*8+j)*16 +: 16]` |
| `r_flat[1023:0]` | out | R row-major; `R[i][j]` at `r_flat[(i*8+j)*16 +: 16]` |
| `done` | out | high when all 64 outputs are valid; held until next `start` |

Operands are presented in parallel and captured into registers on `start`; the
controller then streams the 64 `(i,j)` positions through the pipelined MAC one
per clock. A full 8×8 matmul is **75 cycles** start→done (1 latch + 64 issue +
10 pipeline drain), measured by the cocotb bench.

## Running the bench

Icarus Verilog (built from source, no root) and a cocotb venv are the only
prerequisites. One-time setup:

```bash
# Icarus (into a user prefix; needs a C/C++ toolchain + autotools/flex/bison)
git clone https://github.com/steveicarus/iverilog
cd iverilog && sh autoconf.sh && ./configure --prefix=$HOME/tools/iverilog
make -j && make install

# cocotb venv, alongside this directory
python3 -m venv ../.venv && ../.venv/bin/pip install cocotb
```

Then, from `silicon/rtl/tb`:

```bash
export PATH="$HOME/tools/iverilog/bin:$PATH"   # Icarus on PATH
make                                            # builds libgolden.so + runs all
```

`make` builds `libgolden.so` from the real C sources and runs, in order:
`lns_mul` (2000 random + 81 directed products), `lns_add8` (2000 random + 8
directed reductions), and `lns_matmul_8x8` (the 10 committed board vectors,
byte-exact, plus 20 random 8×8 matmuls). The sibling `../.venv` is put on PATH
automatically. All checks are bit-exact against the C golden — no tolerance band
(the LNS grid + a bit-exact datapath means the RTL reproduces the golden output
exactly, unlike the float-vs-quantized tolerance the cosim testbench uses).

Tests: (a) the 10 committed vectors in `../../board/vectors/` are replayed and
compared byte-for-byte; (b) >4000 random element-level `lns_mul`/`lns_add8`
cases; (c) directed edges — all-zero, saturation at `EXP_MAX`, underflow flush
at `EXP_MIN`, mixed signs, exact cancellation.

Icarus note: SV-2012 packages, packed structs, and functions all worked; the
only adjustment was keeping module ports as flat `logic` vectors (not struct
types) so the bench drives them as plain integers. No package flattening was
needed. Icarus prints two `sorry: constant selects in always_* processes …`
notes for the top's operand-select loop — they are conservative
sensitivity-list fallbacks (the process becomes sensitive to all bits), not
errors, and do not affect results.

## Running the implementation

```bash
source <Xilinx install>/2025.2/Vivado/settings64.sh
cd impl && vivado -mode batch -source run_impl.tcl
```

Post-route reports land in `impl/reports/` (`util_route.rpt`,
`timing_route.rpt`). Project/junk and `reports/` are build output.

## Measured results (Vivado 2025.2, xc7z020clg400-1 @ 10 ns, OOC)

Cocotb: **all suites PASS, bit-exact.** One 8×8 matmul = **75 cycles** start→done.

| Metric | Hand RTL (this dir) | HLS kernel (`../README.md`) |
|---|---|---|
| LUT | **4,271 (8.0 %)** | 8,596 (16.2 %) |
| FF | **3,477 (3.3 %)** | 8,675 |
| DSP | **0** | 0 |
| BRAM_18K | **0** | 2 |
| Timing @ 10 ns | **met, WNS +1.733 ns (8.27 ns ≈ 121 MHz)** | met, 9.362 ns worst (≈107 MHz) |
| Cycles / 8×8 matmul | **75** | 2,979 |
| Initiation | **II=1 per dot product** | II=16 per output element |

### Honesty caveats — read before quoting the table

The two sides are **not kernel-equivalent**, and the differences are structural,
not a win:

1. **The HLS numbers include AXI; this design has none.** The HLS 8,596 LUTs
   include its `s_axilite` control + `m_axi gmem` adapters (~1,350 LUTs of the
   estimate). The 2,979-cycle latency **includes m_axi DDR transfers** of the
   three 8×8 matrices. This design has no AXI, no `m_axi`, no memory subsystem:
   operands are assumed already resident on-chip and are presented in parallel
   on wide ports. So its LUT/FF is a **datapath-only** figure and its 75 cycles
   is **compute-only** — the cost of getting the data on-chip is simply not on
   this side of the table. Do not read "4,271 vs 8,596" as "hand RTL is ~2× smaller
   for the same job," or "75 vs 2,979" as a pure speedup; a fair full-kernel RTL
   would add an AXI wrapper and DMA, which would close much of both gaps.

2. **What the comparison *does* fairly show.** The II gap is real and is the
   actual point: HLS serialized to II=16 per output because one `gmem` bundle
   feeds 2×8 element reads per iteration (a memory-port bottleneck, not an
   arithmetic one). With operands on-chip, the *same datapath* pipelines to II=1
   — the arithmetic was never the limiter. The DSP=0 result also holds on both
   sides: the log-domain MAC maps to LUT fabric, no DSP48s.

3. **DSP-free is enforced, and disclosed.** Left to default inference Vivado maps
   the 16 Mitchell constant-multiplies to **14 DSP48s** (measured). This design
   sets `use_dsp="no"` on `lns_mac8` to force them to LUT fabric, mirroring the
   HLS reference's `BIND_OP … impl=fabric` and honoring the whole premise of LNS
   (replace multipliers with log-domain adds). The 4,271-LUT / 0-DSP row is that
   configuration.

## Deviations from the C model

**None functionally.** Output is bit-exact for every tested input. Two
implementation choices are worth naming because they change *how*, never *what*:

- **`index_of_closest_value` → fixed thresholds.** The C searches 8 abs-diffs
  sequentially; that synthesizes to a deep dependent adder chain. Because the
  Mitchell LUT is sorted, the identical result (including first-minimum tie-break)
  is a set of 7 constant midpoint thresholds. Equivalence was checked
  exhaustively against the C `index_of_closest_value` over the full mantissa
  range, and the whole path is checked end-to-end by the golden compare.
- **Loop reductions written as balanced trees, not accumulate-in-a-loop.** The
  bucket scatter-add and the positive/negative reductions are trees; a literal
  RMW loop with a data-dependent index serializes and will not close 10 ns. Same
  arithmetic, same result — verified bit-exact.

### C-model quirks reproduced verbatim

- The Mitchell `2^(r/8)` LUT and the accumulator's `2^16` scale (`2^QBIAS` from
  the biased-quotient shift, `2^8` from the shifted LUT) — the convert-back undoes
  exactly this.
- The "mantissa past the LUT[7]=470 / 512 midpoint rolls up to the next octave
  (`r=0`, `q+1`)" special case — copied as-is, including the integer `491`
  threshold.
- Exact-zero inputs contribute nothing; a sum that cancels to exactly 0 returns
  the zero element; overflow saturates to `2^7.875`, underflow flushes to zero.
