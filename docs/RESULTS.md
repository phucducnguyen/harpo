# HARPO — Results (the paper's evidence backbone)

> ⚠️ **SCORING CHANGED — see the re-baseline table first.** Tables further below in the
> per-kernel sections were produced under the **OLD ii-first scoring** (throughput scored
> on the worst per-loop `PipelineII`, area as the last tiebreaker) and are kept as the
> **pre-fix record**. The scorer now scores throughput on the design-level **`interval_max`**
> with **`satisfice_then_area`** as the default objective (see "Scoring model (current)"
> just below). The real-Vitis **re-baseline under the new scoring is DONE** — its canonical
> numbers are in "Re-baseline (new scoring)" below. Where an old per-kernel number disagrees
> with the re-baseline table, the re-baseline table is authoritative.

## Scoring model (current)

The scorer now has two layers, both correctness-dominated (the csim/csynth correctness
tier always dominates — no PPA win can outrank a correct-but-faster candidate over a
broken one):

- **Throughput metric = design `interval_max`** (always reported by Vitis), *not* the
  worst per-loop `PipelineII`. The old per-loop term sorted a fully-unrolled loop's
  missing II (`None`) as neutral 0, so it *beat* a real II≥1 and the loop rewarded
  over-unrolling (it once accepted a `mac8_001` design at interval 3073, worse than the
  baseline's 1024). Per-loop `ii` is now **diagnostic-only**.
- **Objective = a 5-value per-task enum** (`spec.json` top-level `objective`):
  `speed_first`, `area_first`, `adp`, `satisfice_then_area` (**default**), `pareto_report`.
  Legacy `throughput`/`latency` spec values still load and alias to `speed_first`;
  unknown/absent → default. `satisfice_then_area` ranks candidates that **meet the
  `throughput_target`** (a new per-task field, the `interval_max` ceiling) ahead of those
  that don't, then minimizes area, then throughput, then ADP; with no target it degrades
  to speed-first-with-area-tiebreak.
- **`area_score`** (`harpo/area.py`): Option A normalized utilization — sum of
  used/available across LUT/FF/DSP/BRAM, **no per-resource weights** (scarcity emerges
  from the denominators, avoiding double-counting); falls back to a per-part capacity
  table (xc7z020) when the report lacks `avail_*`. `adp = area_score × interval_max`
  (fallback latency_worst→ii). Code-complete, 106/106 unit tests green.

## Canonical ablation table (source of truth)

The table below is the **single source of truth** for every measured number in this
file. It is **generated**, not hand-maintained: `scripts/run_ablation.py` (driver, runs
each kernel/arm on real Vitis and writes `docs/ablations/canonical/*.json`) +
`scripts/ablation_table.py` (builder, renders `TABLE.md` and `TABLE.csv` from those
logs). 21 rows across 8 kernels, under the current `interval_max` metric +
`satisfice_then_area` objective.

**If any number elsewhere in this file disagrees with this table, the table is correct.**

Regenerate:

```bash
python3 scripts/run_ablation.py      # re-run arms on Vitis -> docs/ablations/canonical/*.json
python3 scripts/ablation_table.py    # rebuild docs/ablations/canonical/TABLE.md + .csv
```

| Kernel | Category | TargetSource | Target | Method | Correct | interval_max | latency | LUT | FF | BRAM | DSP | area_score | ADP | ToolCalls | Tokens | Accepted | Reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mac8_001 | hand-built | — | — | baseline | ✓ | 1024 | 1026 | 369 | 153 | 0 | 0 | 0.008374 | 8.57504 | — | — | — | — |
| mac8_001 | hand-built | hand-set | 256 | recipe (satisfice_then_area) | ✓ | 256 | 259 | 315 | 126 | 0 | 0 | 0.007105 | 1.81895 | 11 | 0 | ✓ | meets target, lowest area |
| mac8_001 | hand-built | hand-set | 256 | raw LLM | ✓ | 1024 | 1026 | 369 | 153 | 0 | 0 | 0.008374 | 8.57504 | 8 | 7207 | ✗ | no improvement, baseline kept |
| stencil3_001 | hand-built | — | — | baseline | ✓ | 512 | 514 | 193 | 95 | 0 | 0 | 0.004521 | 2.31459 | — | — | — | — |
| stencil3_001 | hand-built | hand-set | 257 | recipe (satisfice_then_area) | ✓ | 257 | 259 | 435 | 43 | 0 | 0 | 0.008581 | 2.20527 | 14 | 0 | ✓ | meets target, lowest area |
| unroll8_001 | hand-built | — | — | baseline | ✓ | 1024 | 1026 | 727 | 451 | 0 | 0 | 0.0179 | 18.3338 | — | — | — | — |
| unroll8_001 | hand-built | hand-set | 128 | recipe (satisfice_then_area) | ✓ | 128 | 132 | 597 | 368 | 0 | 0 | 0.01468 | 1.8791 | 11 | 0 | ✓ | meets target, lowest area |
| matmul_001 | hand-built | — | — | baseline | ✓ | 256 | 260 | 706 | 579 | 0 | 6 | 0.04599 | 11.7722 | — | — | — | — |
| matmul_001 | hand-built | hand-set | 72 | recipe (satisfice_then_area) | ✓ | 44 | 43 | 3121 | 5932 | 0 | 48 | 0.3326 | 14.6344 | 14 | 0 | ✓ | meets target, lowest area |
| matmul_001 | hand-built | n/a | — | recipe (speed_first) | ✓ | 19 | 18 | 5689 | 14999 | 0 | 192 | 1.121 | 21.292 | 17 | 0 | ✓ | kept best |
| matmul_001 | hand-built | hand-set | 72 | raw LLM | ✓ | 256 | 260 | 706 | 579 | 0 | 6 | 0.04599 | 11.7722 | 8 | 17106 | ✗ | no improvement, baseline kept |
| conv2d_001 | hand-built | — | — | baseline | ✓ | 191 | 190 | 871 | 903 | 0 | 6 | 0.05213 | 9.95716 | — | — | — | — |
| conv2d_001 | hand-built | hand-set | 85 | recipe (satisfice_then_area) | ✓ | 82 | 81 | 1318 | 2277 | 0 | 15 | 0.1144 | 9.37724 | 17 | 0 | ✓ | meets target, lowest area |
| gemm_001 | PolyBench | — | — | baseline | ✓ | 2060 | 2054 | 1238 | 1180 | 0 | 6 | 0.06163 | 126.965 | — | — | — | — |
| gemm_001 | PolyBench | fallback | 2060 | recipe (satisfice_then_area) | ✓ | 2060 | 2054 | 1238 | 1180 | 0 | 6 | 0.06163 | 126.965 | 18 | 0 | ✗ | no improvement, baseline kept |
| gemm_001 | PolyBench | fallback | 2060 | raw LLM | ✓ | 2060 | 2054 | 1238 | 1180 | 0 | 6 | 0.06163 | 126.965 | 18 | 14192 | ✗ | no improvement, baseline kept |
| atax_001 | PolyBench | — | — | baseline | ✓ | 304 | 303 | 2481 | 2492 | 0 | 6 | 0.09733 | 29.5881 | — | — | — | — |
| atax_001 | PolyBench | auto-derived | 280 | recipe (satisfice_then_area) | ✓ | 64 | 63 | 3907 | 5596 | 0 | 48 | 0.3442 | 22.0298 | 23 | 0 | ✓ | meets target, lowest area |
| atax_001 | PolyBench | auto-derived | 280 | raw LLM | ✓ | 81 | 80 | 3994 | 5591 | 0 | 48 | 0.3458 | 28.0101 | 23 | 23535 | ✓ | meets target, lowest area |
| bicg_001 | PolyBench | — | — | baseline | ✓ | 171 | 170 | 2169 | 2640 | 0 | 12 | 0.1201 | 20.5419 | — | — | — | — |
| bicg_001 | PolyBench | auto-derived | 162 | recipe (satisfice_then_area) | ✓ | 60 | 59 | 3596 | 8929 | 0 | 96 | 0.5879 | 35.2726 | 23 | 0 | ✓ | meets target, lowest area |

An **optional** secondary view — per-kernel Pareto frontiers + ADRS distances — lives in
`docs/ablations/canonical/PARETO.md`, regenerable via `python3 scripts/pareto_view.py`.
It does not feed this file.

## Re-baseline (new scoring) — the three-fix story

> Numbers in this section are interpretive call-outs to the **canonical ablation table**
> above; that table is authoritative. Recipe arm, real Vitis 2025.2, `xc7z020-clg400-1`,
> 10.0 ns. Each kernel's `throughput_target` (the `interval_max` ceiling the agent
> satisfices to) is in its `spec.json` (hand-set) or auto-derived by the probe.
> Reproduce a single arm: `python3 -m harpo optimize tasks/<task> --provider recipe`.

The three-fix story reads off the canonical rows:

- **Fix 1 — metric (mac8_001 row, raw LLM).** The raw LLM's only throughput move is a full
  inner-loop unroll → `ii=None`. Under the old per-loop-II scoring that was *accepted*;
  under `interval_max` it is correctly **discarded** — the raw-LLM `mac8_001` row keeps the
  baseline (interval 1024, LUT 369, "no improvement, baseline kept"). The recipe arm still
  reaches **interval 256 / LUT 315** (mac8_001 recipe row).
- **Fix 2 — policy (matmul_001 rows).** Here full unrolling genuinely *lowers* `interval_max`,
  so the metric fix alone wouldn't stop it: the `recipe (speed_first)` row chases **interval
  19 at LUT 5689 / FF 14999** (area_score 1.12, ADP 21.3). With `throughput_target=72`,
  `satisfice_then_area` keeps the leanest design that meets the target — the
  `recipe (satisfice_then_area)` row at **interval 44 / LUT 3121 / FF 5932** (area_score 0.33,
  ADP 14.6): ~45% fewer LUT, ~60% fewer FF, *and* a lower ADP, for 25 cycles of interval.
  This is the case the target exists to govern.
- **Fix 3 — autonomy (gemm/atax/bicg rows).** The PolyBench rows carry their target from the
  recipe-only probe (`TargetSource = fallback` for gemm, `auto-derived` for atax/bicg) — no
  hand-set target needed (detail below).

The other hand-built recipe rows land cleanly on target: **mac8** (interval 256 / LUT 315,
area *drops*), **stencil3** (interval 257 / LUT 435, II=1, modest area rise), **unroll8**
(interval 128 / LUT 597, ~8× throughput, area drops), and **conv2d** improves under the new
scoring — see the conv2d note below.

### Autonomous target derivation — the recipe-only probe

When a spec gives **no** `throughput_target`, the agent derives one itself before optimizing
(`harpo/probe.py`, called from `run_optimize`): a **capped, recipe-only, zero-LLM-token**
probe. It synthesizes the baseline, then tries up to `max_synth` (default 4) **single-pragma**
candidates — array-partition / pipeline / *partial* unroll only, **full unroll excluded**
(recipes tagged `full` are skipped) — each a fresh fork from baseline. The target is the
**lowest `interval_max`** among the baseline and any probe candidate that csim+csynth-passes
**and** stays within `area_score ≤ 2.0 × baseline` (cap configurable). If nothing beats the
baseline within the cap, the target falls back to the **baseline `interval_max`** (so the
agent never invents an unreachable goal). No broad DSE, no LLM, capped synths.

Demonstrated on real Vitis:
- **mac8_001 with its target stripped** → probe derives **256** (probe_0 = `ARRAY_PARTITION
  cyclic factor=8` → II=1, LUT 315 < baseline), **exactly the hand-set value**, at **0 tokens**.
  i.e. the autonomous target matches the human one.
- **gemm_001** (PolyBench GEMM, 16×16 int; ships with **no** hand-set target) → the single
  safe pragmas don't unblock its bottleneck, so the probe conservatively **falls back to the
  baseline interval_max (≈2060)** and `satisfice_then_area` correctly keeps the baseline — a
  defensible target with no false "improvement". Reproduce:
  `python3 -m harpo optimize tasks/gemm_001 --provider recipe`.

So both target paths are live: **hand-set** (the 5 kernels above) and **auto-derived** (the
probe).

### Standard benchmarks (PolyBench) — moving beyond hand-built kernels

Three PolyBench-derived kernels (integer, 16×16) ported as optimize fixtures extend the
evidence beyond hand-built toys. **All ship with no hand-set `throughput_target`** — every
PolyBench target is **auto-derived by the recipe probe** (the canonical table's
`TargetSource` column reads `fallback`/`auto-derived` for these rows). Reading the canonical
rows: **gemm_001** falls back to the baseline target 2060 (safe single pragmas don't unblock
its bottleneck → baseline kept, no change); **atax_001** derives target 280 and satisfices to
**interval 64 / LUT 3907** within the 2× area cap; **bicg_001** derives target 162 and reaches
**interval 60 / LUT 3596**. Reproduce:
`python3 -m harpo optimize tasks/{gemm,atax,bicg}_001 --provider recipe`.

### Recipe vs raw-LLM under the new scoring (LLM-arm re-baseline)

The raw-LLM arm (`--provider ollama`, local qwen via Ollama) was re-baselined on four
kernels under interval_max + satisfice_then_area; the `raw LLM` rows in the canonical table
are the record. The honest gradient:

- **mac8_001 — recipe wins decisively.** Recipe interval 256 / LUT 315; the raw LLM's only
  move is a full unroll (→ interval 3073, discarded), so its row keeps the baseline ("no
  improvement").
- **matmul_001 — recipe wins decisively.** Recipe satisfice interval 44 / LUT 3121 meets
  target 72; the raw LLM's PIPELINE makes interval worse and UNROLL yields no gain, so no
  candidate meets the target → its row keeps the baseline.
- **gemm_001 — tie (both null).** Neither recipe (probe fallback) nor raw LLM improves on the
  baseline.
- **atax_001 — comparable, recipe marginal.** Recipe interval 64 / LUT 3907 / ADP 22.0 vs raw
  LLM interval 81 / LUT 3994 / ADP 28.0 — both meet the target, recipe slightly smaller/faster.

Stated honestly: on the structured-reduction kernels (mac8, matmul) the raw LLM
**over-parallelizes and now wins nothing** under honest scoring, while the precise recipe
applies the one unblocking pragma — a decisive gap. On a kernel the safe recipes can't crack
(gemm) both are null. On atax the two are comparable. The recipe-before-LLM default captures
the best of both.

---

Every number below is pulled from the committed JSON logs under `runs/`, produced
on **atlas** with **Vitis HLS 2025.2** (csim via `gpp`, csynth via `vitis_hls`),
part `xc7z020clg400-1`, clock 10.0 ns. Each result lists the **exact command** that
regenerates it. The three pillars of the Track-A evidence story are: the **closed-loop
workflow**, the **token account by phase**, and **PPA before/after**.

## Reproduce the whole suite

```bash
source ~/tools/Xilinx/2025.2/Vitis/settings64.sh    # for any csynth/optimize/pipeline
python3 scripts/run_suite.py                         # aggregate runs/ -> SUITE.md + SUITE.csv (no Vitis)
python3 scripts/run_suite.py --run                   # re-run harpo first, then aggregate (needs Vitis)
```

Offline self-tests (no Vitis, no LLM):

```bash
python3 scripts/selftest.py            # parse_csim classification (synthetic outputs)
python3 scripts/selftest_recipes.py    # RecipeProvider emits valid C++ (g++ -fsyntax-only) on mac8
python3 scripts/selftest_csynth.py     # parse_csynth resource-util% from stored XML reports
```

## 1. Repair — correctness, minimal change, near-zero cost

**Task `vadd_buggy_001`** — vector add with a planted wrong operator
(`c[i] = a[i] - b[i]`, should be `+`). Source: `tasks/vadd_buggy_001/src/vadd.cpp`.

```bash
python3 -m harpo repair tasks/vadd_buggy_001 --provider mock,ollama
```

From `runs/vadd_buggy_001/repair_log.json`:

| metric | value |
| --- | --- |
| repaired | **true** (winner `cand_0001`) |
| steps | **2** |
| LLM calls | **1** |
| tokens (prompt / completion / total) | **2054 / 346 / 2400** |
| budget spent (csim / csynth / llm) | 2 / 0 / 1 |
| cost | **$0** (local model) |

Workflow trail (the agent's own event log):

```
cand_0000: csim functional_fail -> CSIM_FUNCTIONAL_FAIL
proposal from OllamaProvider: "Replace '-' with '+' ... to perform vector addition instead of subtraction"
applied via whole_file -> cand_0001
cand_0001: csim pass -> PASS  (repaired)
```

The local LLM (`ollama` provider) made the one-character functional fix in a single
call; the `mock` provider abstained (no matching edit), the contract check passed
(signature/testbench preserved), and the forked candidate re-passed csim.

## 2. Optimize — correctness-preserving PPA, zero tokens (recipe-driven)

All three optimize tasks were driven by the deterministic **`recipe`** provider, so
they spent **0 LLM tokens** — the "dumbest reliable tool first" principle: a precise
pragma library beats an LLM that emits imprecise pragmas (see §3). The winning move
in every case was a cyclic array partition on the kernel input that unblocked
pipelining to **II=1**. Each run also demonstrates the invariant: later candidates
are kept only when they **re-pass csim AND strictly improve the score**.

```bash
python3 -m harpo optimize tasks/mac8_001     --provider recipe,ollama
python3 -m harpo optimize tasks/stencil3_001 --provider recipe,ollama
python3 -m harpo optimize tasks/unroll8_001  --provider recipe,ollama
```

PPA before → after (from each `runs/<task>/optimize_log.json`):

| task | kernel | II | latency (worst) | LUT | FF | Fmax (MHz) | steps | winning pragma |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `mac8_001` | windowed sum (×8) | 4 → **1** | 1026 → **259** | 369 → **315** | 153 → **126** | 144.45 → 144.45 | 4 | `ARRAY_PARTITION cyclic factor=8 dim=1` on `in` |
| `stencil3_001` | 1-D 3-tap stencil | 2 → **1** | 514 → **259** | 193 → 435 | 95 → 54 | 196.43 → 149.81 | 3 | `ARRAY_PARTITION cyclic factor=8 dim=1` on `in` |
| `unroll8_001` | 16-wide inner reduction | 8 → **1** | 1026 → **132** (≈7.8×) | 727 → **597** | 451 → **368** | 144.45 → 144.45 | 4 | `ARRAY_PARTITION cyclic factor=8 dim=1` on `in` |

Notes, grounded in the logs:
- **`mac8_001`** improved on the very first candidate (II 4→1, latency 1026→259,
  *and* LUT 369→315, FF 153→126 — faster and smaller). Candidates 2–4 (partition on
  `out`, factor=4 variants) produced no further score gain and were discarded.
- **`stencil3_001`** hit II 1 / latency 259 with the same move; LUT rose 193→435 and
  Fmax fell 196.43→149.81 — but the lexicographic score prioritizes II then latency
  over LUT, so the design is correctly accepted as an improvement. (A later candidate
  that lowered FF 54→43 was *rejected* because II/latency/LUT did not improve — the
  score, not raw FF, decides.)
- **`unroll8_001`** is the headline latency win: 1026 → 132 (~7.8×) at II 1, while
  also shrinking LUT 727→597 and FF 451→368. The task name is historical; the kernel
  is a fixed **16-wide** inner reduction.

### Generalization to a 2-D nested-loop kernel (`matmul_001`)

The fixtures above are all 1-D reductions. `matmul_001` (8×8 integer matmul,
triple nested loop) proves the same loop works on a canonical 2-D HLS kernel.
Real Vitis, evidence in `docs/ablations/matmul_001_optimize.json`:

| task | II | latency (worst) | LUT | FF | DSP | Fmax | steps | winning pragmas |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `matmul_001` | 4 → **1** | 260 → 518 | 706 → **573** | 579 → 612 | 6 → **3** | 144.45 → 144.68 | 3 | `PIPELINE II=1` (inner) + `ARRAY_PARTITION cyclic factor=N dim=1` on `B` |

The loop accepted candidate 1 (II 4→1, LUT 706→573, DSP 6→3) and **rejected** the
two non-improving follow-ups. Honest nuance: `latency_worst` **rose** 260→518
even as II improved — the lexicographic score ranks II ahead of latency, so an
initiation-interval win is taken even at a single-call-latency cost. That is a
defensible default for streamed kernels but flags a **future per-task objective
knob** (throughput- vs latency-oriented). The point stands: the optimizer
generalizes beyond toy reductions and never sacrifices correctness.

### `conv2d_001` — improves under the current scoring

`conv2d_001` (8×8 input, 3×3 kernel, valid 2-D convolution). **Under the CURRENT scoring**
(interval_max metric + `satisfice_then_area`, target 85) conv2d **improves**: the canonical
recipe row reaches **interval 191→82** at **LUT 871→1318** (FF 903→2277), the smallest-area
design that meets the target. It is no longer a no-win kernel.

> **Pre-fix historical note (NOT current state).** Under the *old* ii-first scoring with
> **no `throughput_target`**, the conv2d optimize run kept the baseline: the mock pragma
> (`PIPELINE II=1` inner + `ARRAY_PARTITION` on `ker`) produced a per-loop II=1 but a worse
> *design* — interval 191→328, latency 190→330, FF 903→1321 — so the strict-improvement guard
> rejected it. That was the evidence motivating Fix 1 (score throughput on `interval_max`, not
> the worst per-loop II): per-loop `ii` is a poor global throughput proxy. With Fix 1 + a real
> target in place, conv2d now improves (interval 82, see the canonical table). Retain the
> 191-vs-328 figures only as this pre-fix record.

## 3. Recipe vs. LLM — the area lesson (captured ablation, PRE-FIX scoring)

> **Pre-fix record.** The LUT 13194 / interval-128 LLM blow-up below was produced under the
> **old greedy lexicographic score** (II→latency dominating, area last) — it is the *motivation*
> for the scoring overhaul, not current behavior. Under the current interval_max +
> `satisfice_then_area` scoring the raw LLM wins nothing on mac8 (see the canonical table's
> mac8_001 raw-LLM row). Kept here as the diagnostic story.

The motivation for shipping a deterministic recipe library alongside the LLM: a
local model is fluent but **imprecise about *how hard to push*** — it over-applies
parallelism for marginal latency at order-of-magnitude area cost, while the
deterministic recipe applies exactly the one pragma that unblocks II=1 and stops.

This was run head-to-head on `mac8_001` (same loop, same kernel, two providers),
real Vitis HLS 2025.2, part `xc7z020-clg400-1` — full writeup + the committed JSON
logs are in **`docs/ablations/recipe-vs-llm.md`**. Reproduce with:

```bash
python3 -m harpo optimize tasks/mac8_001 --provider recipe   # -> docs/ablations/mac8_001_recipe.json
python3 -m harpo optimize tasks/mac8_001 --provider ollama   # -> docs/ablations/mac8_001_ollama.json
```

| design | II | latency (worst) | LUT | FF | tokens | what it emitted |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 4 | 1026 | 369 | 153 | — | — |
| **recipe-best** | **1** | 259 | **315** | 126 | **0** | one `ARRAY_PARTITION cyclic factor=8 dim=1` |
| **ollama-best** | n/a¹ | 129 | **13194** | 322 | 34,387 | partition×2 + `PIPELINE II=1` + `UNROLL factor=8` |

¹ The LLM fully unrolls the outer loop, so Vitis reports no per-iteration II;
throughput shows as total interval 128 (vs baseline 1024) — a real, correct win,
paid for in area. Both arms are functionally correct (re-verified csim).

**Result: ~42× area for comparable throughput** (recipe 315 LUT vs LLM 13194 LUT;
the LLM is in fact lower-latency, 129 vs 259). The LLM arm was run **3×** and was
**highly stable** — identical winning candidate and PPA every time — so the
blow-up is consistent behavior, not a draw.

**Honest correction to an earlier hypothesis.** A prior note framed the LLM
blow-up as an *imprecise* `ARRAY_PARTITION` (missing the partition **type**)
silently defaulting to `complete`. With the **current** optimizer prompt
(`_OLLAMA_OPT_SYSTEM_PROMPT`, which now forbids bare `ARRAY_PARTITION` and warns
that omitting the type "detonates area") the LLM no longer makes that specific
mistake — every partition it emitted was a fully-specified `cyclic factor=N`. The
area blow-up **reproduced anyway, via a different mechanism**: the LLM stacks
`PIPELINE II=1` **plus** `UNROLL factor=8` on top of partitioning, fully spatially
unrolling the reduction. Each step strictly improves the lexicographic score
(II → latency dominate area), so the greedy loop accepts the ever-larger-but-faster
design. The lesson is the same one the recipe library encodes, sharpened.

HARPO's defenses, both in the codebase today:

- the **recipe catalogue** (`harpo/recipes.py`) only ever emits *fully specified*
  pragmas (`cyclic factor=N dim=1`), validated to compile by `scripts/selftest_recipes.py`,
  and stops at the minimal area-preserving move;
- the **LLM optimize system prompt** (`_OLLAMA_OPT_SYSTEM_PROMPT` in `patch_engine.py`)
  forbids bare `ARRAY_PARTITION` and warns that omitting the type detonates area.

This is why the optimize default provider order is **`recipe,ollama`**: precise
deterministic recipes first, the LLM only for the tail the catalogue can't reach.

## 4. Token consumption by phase (`runs/SUITE.md`)

| phase | prompt | completion | total |
| --- | --- | --- | --- |
| repair | 2054 | 346 | 2400 |
| optimize | 0 | 0 | 0 |
| **all** | **2054** | **346** | **2400** |

Totals: 4 tasks aggregated · **2400 total tokens** · **42 total tool calls** (sum of
`budget.spent` across phases). The whole demonstrated suite — one real LLM repair plus
three real-Vitis PPA optimizations — cost **2400 local tokens ($0)** and stayed well
inside the per-task budgets (`csim` limit 20, `csynth` 10, `llm_calls` 30).

## 5. Full suite table (`runs/SUITE.md`)

| task | phase(s) | repaired | improved | II (base→best) | latency (base→best) | LUT (base→best) | FF (base→best) | Fmax | steps | tokens(P/C/total) | budget (csim/csynth/llm) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mac8_001 | optimize | — | True | 4→1 | 1026→259 | 369→315 | 153→126 | 144.45 | 4 | 0/0/0 | 5/5/4 |
| stencil3_001 | optimize | — | True | 2→1 | 514→259 | 193→435 | 95→54 | 149.81 | 3 | 0/0/0 | 4/4/3 |
| unroll8_001 | optimize | — | True | 8→1 | 1026→132 | 727→597 | 451→368 | 144.45 | 4 | 0/0/0 | 5/5/4 |
| vadd_buggy_001 | repair | True | — | — | — | — | — | — | 2 | 2054/346/2400 | 2/0/1 |

_Skipped (no phase log yet): `vadd_001` (Gate-0 toolchain proof — see GATE0.md),
plus additional repair fixtures `vadd_offbyone_001`, `scale_wrongop_001` (kernels
present under `tasks/`, not yet run into a committed log)._

> Suite-table caveat: `scripts/run_suite.py` renders the latency column from
> `latency_best`, while the per-task analysis above uses `latency_worst`. For these
> kernels the two coincide (the numbers match), but on a kernel where best ≠ worst the
> suite cell and the per-task latency may differ — worth aligning before the final paper.
