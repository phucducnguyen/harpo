# HARPO: A Budget-Aware Agent that Repairs then Optimizes HLS C/C++

*FPT'26 AMD FPGA Design Competition — Track A (LLM4HLS) — paper draft*

> Draft for the official IEEE conference double-column template (max **2 pages** main
> content + unlimited appendices; confirmed 2026-06-20 from the official FPT'26 page).
> Markdown now; format to the official layout later. The preliminary stage is a
> **double-blind** peer review, so the camera-ready PDF must be anonymized before the
> 2026-08-01 submission — not done in this draft. Every quantitative claim traces to a
> committed doc (RESULTS.md / recipe-vs-llm.md / GATE0.md / ARCHITECTURE.md). TODO
> placeholders are marked inline and listed at the end.

## Abstract

HARPO is a budget-aware autonomous agent for High-Level Synthesis (HLS) that
**repairs** a broken C/C++ kernel to functional correctness and then **optimizes**
its performance/power/area (PPA) — under a *strict per-task tool-invocation budget*,
following Track A's ranking rule of **correctness before PPA**. It is a closed control
loop (run tool → parse report → diagnose → propose one minimal change → verify →
keep/rollback), not a one-shot prompt. Three design choices make it competitive: a
**BudgetManager** that accounts every csim/csynth/LLM call and gates the policy
(no synthesis before csim passes; stop on repeat/regress; reserve held for final
verification); a hard **correctness-preserving invariant** (every optimization is
re-run through csim *before* its synthesis metrics are even read, and kept only if it
*strictly* improves a lexicographic, correctness-dominated score); and a deterministic
**precise-pragma recipe library** placed *ahead of* the LLM. The agent runs entirely on
a **local, free** qwen model (Ollama over HTTP) at **$0** LLM cost. On real Vitis HLS
2025.2 (atlas, part `xc7z020clg400-1`, 10 ns) the demonstrated suite — one LLM repair
plus four real-Vitis PPA optimizations — repaired a planted bug in 2 steps / 1 LLM call
/ 2400 tokens, drove kernels to **II=1** (up to ~7.8× latency on `unroll8_001`), and
generalized to a 2-D matmul. Our distinctive finding is that a raw LLM
**over-parallelizes**: on `mac8_001` it once reached comparable throughput at **13194 LUT
(~42×** the deterministic recipe's **315 LUT)** for **34,387 tokens** — both correct.
That ~42× number is, however, a product of the *original* greedy scoring; it is the
motivating finding, not a current result. HARPO's corrected scoring
(throughput on the design `interval_max` plus a default `satisfice_then_area` objective)
now **rejects** that area blow-up — the recipe-first ordering captures the lesson
structurally, and the canonical evidence table
(`docs/ablations/canonical/TABLE.md`) is the current source of truth.

## 1. Approach / Architecture

HARPO is built from six cooperating components and two control loops.

**Components.**
1. **Task loader** — normalizes a competition-style bundle (`spec.json` +
   `constraints.json` + `budget.json`) into one `TaskContext` (top function, source/
   testbench file lists, part, clock, policy, budget). Part/clock/sources are *injected*,
   never hardcoded, so the same agent runs the evaluator's tasks unchanged.
2. **Tool runner** — dispatches a stage to a backend: `gpp` (host g++ compile+run =
   functional csim, no Vitis needed, since g++ ignores `#pragma HLS`) or `vitis_hls`
   (real csim+csynth via a generated `run_harpo.tcl`).
3. **Report parser** — `parse_csim` → {pass, compile_error, functional_fail, timeout,
   tool_unavailable}; `parse_csynth` → II, depth, latency best/worst, Fmax,
   LUT/FF/DSP/BRAM + util% from the Vitis XML, with timing/resource violations.
4. **Diagnosis engine** — rule-based, deterministic (no model): maps a parsed status to
   a recommended action; a clean/improvable csynth pass yields `optimize_ppa`, a repeated
   failure escalates to `rollback_or_escalate`.
5. **Patch providers** — a uniform `PatchProvider` protocol with three implementations:
   `mock` (deterministic string edits, for tests/demo), `recipe` (deterministic
   precise-pragma library, no tokens), and `ollama` (local LLM over stdlib `urllib`,
   never raises — degrades to the next provider). Each reports `last_usage` tokens.
6. **Candidate store + lexicographic score** — every attempt is an isolated, forkable
   copy of the source; the edited kernel is compiled against the *un-edited* testbench;
   the winner is whichever candidate scores highest. The **BudgetManager** is the
   Track-A spine (per-tool limits + reserve + policy gates).

**The two loops.**

```
 REPAIR (correctness):                    OPTIMIZE (PPA, never breaks correctness):
   csim (gpp) ──> parse ──> diagnose         baseline csim MUST pass ──┐ else "run repair first"
        │ pass? ── yes ──> DONE (winner)            │                  │
        │ no                                   baseline csynth ──> baseline_metrics
   budget.policy_allows(llm)?                        │
        │ yes                                   loop (while steps<max, no_improve<patience):
   provider.propose() (recipe→ollama)            diagnose_csynth ──> provider.propose()
        │  (accumulate tokens)                        │
   check_contract (sig/tb/glob)                  check_contract; fork; apply_patch
        │ ok                                          │
   fork + apply_patch ──> loop                   ★ RE-VERIFY csim  ── broke? ──> DISCARD
                                                      │ still pass
   stop: csim pass · max_steps ·                 csynth(child)
         budget exhausted · repeat/regress            │
                                                  score(child) > score(best)?  (strict)
                                                      │ yes ──> ACCEPT   │ no ──> REJECT
```

`run_pipeline` chains them on **one** shared per-task `BudgetManager`, so repair and
optimize debit the same account.

**BudgetManager (the Track-A spine).** Constructed from `budget.json`
(`mode: per_tool`, limits `{static_check:100, csim:20, csynth:10, cosim:5,
llm_calls:30}`, `reserve {final_csim:1, final_csynth:1, final_cosim:1}`). A missing
limit is unlimited. `can(action)` is true only while `spent < limit − reserve` — the
reserve guarantees a winner can always be re-verified at the end. `policy_allows`
enforces, in order: (1) budget; (2) **stage ordering** — no csynth/cosim before csim
passes; (3) **stop/rollback guard** — refuse another LLM call when the state is
*repeated* or *regressed*.

**Score (correctness-dominated).** (1) **correctness tier** — 0 csim
unknown/fail, 1 csim pass, 2 csim+csynth pass (a tier-2 candidate always outranks a
tier-1, regardless of PPA); then within a tier the ranking is **throughput on the
design `interval_max`** (not the per-loop II — that is diagnostic-only), refined by an
**objective-dependent** secondary order. The default objective is `satisfice_then_area`:
once a candidate meets the per-task `throughput_target` it is ranked by lowest normalized
`area_score`, then ADP (area × interval). The other objectives (`speed_first`,
`area_first`, `adp`, `pareto_report`) reorder these terms; the old II-first, latency,
LUT lexicographic order is no longer the live score (see §3.5 for why it was replaced).

**The correctness invariant.** An optimization is accepted only if it (a) still passes
csim AND (b) strictly improves the score. Every forked candidate is re-run through csim
*before* its csynth metrics are read; if a pragma broke functional behavior, the
candidate is discarded and its metrics are never trusted. This is the structural
guarantee behind "correctness before PPA": the agent can never trade a wrong-but-fast
design up the ranking. (Proven by a hermetic test, `tests/test_optimize_safety.py`
with `tasks/trap_breakscsim_001`; 106 unit tests total, all green — HANDOVER.md.)

## 2. The recipe library and the recipe-vs-LLM finding

The deterministic **recipe library** (`recipes.py`) emits *fully specified*,
correct-by-construction HLS pragmas one per call by robust text scanning
(`ARRAY_PARTITION cyclic factor=N dim=1`, `PIPELINE II=1`, `UNROLL factor=N`, …),
validated to compile by an offline g++ syntax self-test. It costs **0 tokens**. The
optimize default provider order is **`recipe,ollama`** — precise deterministic recipes
first, the LLM only for the tail the catalogue can't reach ("dumbest reliable tool
first").

**The headline ablation** (RESULTS.md §3, `docs/ablations/recipe-vs-llm.md`): the same
optimize loop, the same kernel `mac8_001`, two providers, real Vitis HLS 2025.2:

| design | II | latency (worst) | interval | LUT | FF | tokens (P/C/total) | what it emitted |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 4 | 1026 | 1024 | 369 | 153 | — | — |
| **recipe-best** | **1** | 259 | 256 | **315** | 126 | 0/0/**0** | one `ARRAY_PARTITION cyclic factor=8 dim=1` |
| **ollama-best** | n/a¹ | **129** | 128 | **13194** | 322 | 32747/1640/**34387** | partition×2 + `PIPELINE II=1` + `UNROLL factor=8` |

¹ The LLM fully unrolls the outer loop, so Vitis reports no per-iteration II
(`ii: null`); throughput shows as total interval 128 (vs baseline 1024) — a real,
correct throughput win, paid for in area. Both arms re-verified csim-correct.

**~42× area for comparable throughput** (recipe 315 LUT vs LLM 13194 LUT; the LLM is in
fact lower-latency, 129 vs 259). For `xc7z020` (53,200 LUT) the recipe sits at 0.6%
utilization, the LLM design at 24%. The LLM arm was run **3×** and was **highly stable**
— identical winning candidate, four-pragma stack, and PPA (LUT 13194, latency 129, FF
322, 34,387 tokens) every time. The blow-up is consistent behavior, not a draw.

**Honest cause (corrected from an earlier hypothesis).** A prior note framed the
blow-up as an *imprecise* `ARRAY_PARTITION` (missing the partition type) defaulting to
`complete`. With the current optimizer prompt (`_OLLAMA_OPT_SYSTEM_PROMPT`, which
forbids bare `ARRAY_PARTITION` and warns that omitting the type "detonates area") the
LLM no longer makes that mistake — every partition it emitted was a fully-specified
`cyclic factor=N`. The area blow-up **reproduced anyway, via a different mechanism**:
the LLM stacks `PIPELINE II=1` *plus* `UNROLL factor=8` on top of partitioning, fully
spatially unrolling the reduction. Each step strictly improves the lexicographic score
(II → latency dominate area), so the greedy loop accepts the ever-larger-but-faster
design. The lesson is the same one the recipe encodes, sharpened: **a raw LLM is fluent
but imprecise about *how hard to push*** — it over-applies parallelism for marginal
latency at order-of-magnitude area cost, while the recipe applies exactly the one pragma
that unblocks II=1 and stops.

Crucially, a follow-up re-ablation (`recipe-vs-llm.md`) traced the *enabler* of the
blow-up to the **score itself**, not the LLM: a fully-unrolled loop reports no per-loop
II (`None`), which the old throughput term sorted as neutral and thus ranked *above* a real
II≥1 — so the loop literally rewarded over-unrolling (it even accepted a design with
interval 3073 vs the baseline's 1024). Prompt hardening alone does not fix this. **Both
durable fixes are now implemented (§3.5):** *Fix 1 (metric)* scores throughput on the
design `interval_max` rather than the per-loop II; *Fix 2 (policy)* makes the default
objective `satisfice_then_area` rather than speed-first.

## 3. Results

All numbers below are from the committed JSON logs under `runs/` and `docs/ablations/`,
produced on **atlas** with **Vitis HLS 2025.2** (csim via `gpp`, csynth via
`vitis_hls`), part `xc7z020clg400-1`, clock 10.0 ns (GATE0.md: Gate-0a and Gate-0b
PASSED).

### 3.1 Repair — correctness, minimal change, near-zero cost

Task `vadd_buggy_001` — vector add with a planted wrong operator
(`c[i] = a[i] - b[i]`, should be `+`). From `runs/vadd_buggy_001/repair_log.json`:

| metric | value |
| --- | --- |
| repaired | true (winner `cand_0001`) |
| steps | 2 |
| LLM calls | 1 |
| tokens (prompt / completion / total) | 2054 / 346 / 2400 |
| budget spent (csim / csynth / llm) | 2 / 0 / 1 |
| cost | $0 (local model) |

Event trail: `cand_0000` csim functional_fail → the local LLM proposes "replace '-'
with '+'" → applied whole-file → `cand_0001` csim pass (repaired). The `mock` provider
abstained; the contract check (signature/testbench preserved) passed.

### 3.2 Optimize — correctness-preserving PPA, zero tokens (recipe-driven)

PPA before → after, from each `runs/<task>/optimize_log.json`:

| task | kernel | II | latency (worst) | LUT | FF | Fmax (MHz) | steps | winning pragma |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `mac8_001` | windowed sum (×8) | 4 → **1** | 1026 → **259** | 369 → **315** | 153 → **126** | 144.45 → 144.45 | 4 | `ARRAY_PARTITION cyclic factor=8 dim=1` on `in` |
| `stencil3_001` | 1-D 3-tap stencil | 2 → **1** | 514 → **259** | 193 → 435 | 95 → 54 | 196.43 → 149.81 | 3 | `ARRAY_PARTITION cyclic factor=8 dim=1` on `in` |
| `unroll8_001` | 16-wide inner reduction | 8 → **1** | 1026 → **132** (≈7.8×) | 727 → **597** | 451 → **368** | 144.45 → 144.45 | 4 | `ARRAY_PARTITION cyclic factor=8 dim=1` on `in` |

- `mac8_001` improved on the first candidate (II 4→1, latency 1026→259, *and* smaller:
  LUT 369→315, FF 153→126); later candidates produced no further gain and were
  discarded.
- `stencil3_001` hit II=1 / latency 259; LUT rose 193→435 and Fmax fell 196.43→149.81,
  but the lexicographic score prioritizes II then latency over LUT, so it is correctly
  accepted. A later candidate that lowered FF 54→43 was *rejected* because II/latency/LUT
  did not improve — the score, not raw FF, decides.
- `unroll8_001` is the headline latency win: 1026 → 132 (~7.8×) at II=1, also shrinking
  LUT and FF. (Name is historical; the kernel is a fixed 16-wide inner reduction.)

**Generalization to a 2-D nested-loop kernel** — `matmul_001` (8×8 integer matmul,
triple-nested loop), real Vitis, evidence in `docs/ablations/matmul_001_optimize.json`:

| task | II | latency (worst) | LUT | FF | DSP | Fmax | steps | winning pragmas |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `matmul_001` | 4 → **1** | 260 → 518 | 706 → **573** | 579 → 612 | 6 → **3** | 144.45 → 144.68 | 3 | `PIPELINE II=1` (inner) + `ARRAY_PARTITION cyclic factor=N dim=1` on `B` |

The loop accepted candidate 1 (II 4→1, LUT 706→573, DSP 6→3) and rejected the two
non-improving follow-ups. Honest nuance: `latency_worst` **rose** 260→518 even as II
improved — the lexicographic score ranks II ahead of latency, so an initiation-interval
win is taken even at single-call-latency cost (see §4).

### 3.3 Token consumption by phase (`runs/SUITE.md`)

| phase | prompt | completion | total |
| --- | --- | --- | --- |
| repair | 2054 | 346 | 2400 |
| optimize | 0 | 0 | 0 |
| **all** | **2054** | **346** | **2400** |

Totals: 4 tasks aggregated · **2400 total tokens** · **42 total tool calls** (sum of
`budget.spent` across phases). The whole demonstrated suite — one real LLM repair plus
three real-Vitis PPA optimizations — cost **2400 local tokens ($0)** and stayed well
inside the per-task budgets (csim limit 20, csynth 10, llm_calls 30).

### 3.4 Full suite table (`runs/SUITE.md`)

| task | phase | repaired | improved | II (base→best) | latency (base→best) | LUT (base→best) | FF (base→best) | Fmax | steps | tokens (P/C/total) | budget (csim/csynth/llm) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mac8_001 | optimize | — | True | 4→1 | 1026→259 | 369→315 | 153→126 | 144.45 | 4 | 0/0/0 | 5/5/4 |
| stencil3_001 | optimize | — | True | 2→1 | 514→259 | 193→435 | 95→54 | 149.81 | 3 | 0/0/0 | 4/4/3 |
| unroll8_001 | optimize | — | True | 8→1 | 1026→132 | 727→597 | 451→368 | 144.45 | 4 | 0/0/0 | 5/5/4 |
| vadd_buggy_001 | repair | True | — | — | — | — | — | — | 2 | 2054/346/2400 | 2/0/1 |
| conv2d_001 | optimize | — | **False** (baseline kept) | none→1¹ | 190→190 | 871→871 | 903→903 | 123.76 | 2 | 0/0/0 | 3/3/2 |

¹ **Pre-fix row (old ii-first scoring, no target).** Under the old scoring the
`conv2d_001` (8×8 / 3×3 valid conv) run kept the baseline: the mock pragma produced
a per-loop II=1 but a *worse* design — interval 191→**328**, latency 190→**330**,
FF 903→1321 — so the strict-improvement guard rejected it. This exposed the scoring
finding behind Fix 1 (score throughput on the design `interval_max`, not the per-loop
worst II; §3.5). **Under the current scoring conv2d IMPROVES** — interval 191→**82**,
LUT 871→**1318** at target 85 (see §3.6 / the canonical table); the "no-win" framing
here is pre-fix only.

### 3.5 The scoring overhaul — two fixes, implemented

The over-parallelization enabler (§2) is **two distinct defects** with **two distinct
fixes**, both implemented and **re-baselined on real Vitis** (106/106 unit tests green; the
re-baseline numbers are in §3.6, and the §3.1–§3.4 tables are the *pre-fix* record). The full
evidence table (21 rows / 8 kernels) and the optional Pareto/ADRS appendix are regenerable via
`scripts/ablation_table.py` (→ `docs/ablations/canonical/TABLE.md`) and `scripts/pareto_view.py`
(→ `PARETO.md`):

- **Fix 1 — metric: throughput is scored on the design `interval_max`, not the per-loop
  `PipelineII`.** The per-loop term sorted a fully-unrolled loop's missing II (`None`) as
  neutral 0, beating a real II≥1 and rewarding over-unrolling. `interval_max` is always
  reported by Vitis; per-loop `ii` is now diagnostic-only. Under it the accepted
  `mac8_001` interval-3073 design correctly loses to the baseline (1024), and the old
  `conv2d_001` over-pragma'd candidate (interval 328) correctly loses to the baseline (191)
  — while the proper recipe move now drives conv2d to interval 82 under a target (§3.6).
- **Fix 2 — policy: the default objective is `satisfice_then_area`.** The per-task
  objective is a 5-value enum — `speed_first`, `area_first`, `adp`, `satisfice_then_area`
  (default), `pareto_report` (`spec.json` `objective`; legacy `throughput`/`latency` alias
  to `speed_first`; unknown/absent → default). `interval_max` scoring alone does not stop
  a *genuinely faster but huge* design from winning on throughput; satisficing throughput
  to a per-task `throughput_target` and then minimizing area is what makes the elegant
  recipe (interval 256 / 315 LUT) outrank the LLM blow-up (128 / 13194 LUT).

Supporting these, a new `harpo/area.py` provides a normalized `area_score`
(used/available summed over LUT/FF/DSP/BRAM, no per-resource weights so scarcity is not
double-counted; per-part fallback for xc7z020), `adp = area_score × interval_max`,
`resource_growth_ratio`, and a `pareto_front` helper for the reporting mode. A new
per-task `throughput_target` field carries the `interval_max` ceiling the satisfice policy
targets.

- **Fix 3 — autonomy: a recipe-only capped probe derives the target when the task gives
  none.** `satisfice_then_area` needs a `throughput_target`; rather than require a
  hand-written one, `harpo/probe.py` derives it. The probe is deliberately minimal:
  **recipe-only, zero LLM tokens**, capped at `max_synth` single-pragma forks from the
  baseline (default 4), **full unroll excluded**. The target is the lowest `interval_max`
  among the baseline and any probe candidate that csim+csynth-passes *and* stays within
  `area_score ≤ 2× baseline`; if nothing beats the baseline within that cap, it falls back
  to the baseline `interval_max` (never an unreachable goal). This makes the objective
  autonomous: on `mac8_001` with its target stripped, the probe derives **256** — exactly
  the hand-set value — at 0 tokens.

### 3.6 Re-baseline under the new scoring, and the recipe-vs-LLM picture

Recipe arm, real Vitis 2025.2, `xc7z020-clg400-1`, 10 ns. Every number here is a row in the
canonical evidence table (`docs/ablations/canonical/TABLE.md`, regenerable via
`scripts/ablation_table.py`; the Pareto/ADRS appendix via `scripts/pareto_view.py`). The two
fixes show on two kernels:

- **`mac8` (Fix 1, metric).** Full unroll makes `interval_max` *worse* (3073) → Fix 1 discards
  it, and the recipe reaches interval 256 / LUT 315.
- **`matmul` (Fix 2, policy).** Full unroll makes `interval_max` genuinely *better*, so the
  metric fix alone won't stop it. The two matmul recipe rows make the case directly:
  **`speed_first` reaches interval 19 / LUT 5689 / FF 14999 (area_score 1.12, ADP 21.3)**,
  while **`satisfice_then_area` (target 72) keeps interval 44 / LUT 3121 / FF 5932
  (area_score 0.33, ADP 14.6)** — ~45% fewer LUT, ~60% fewer FF, *and* a lower ADP, for 25
  cycles of interval. The target is what governs the over-push.

Three PolyBench kernels (gemm/atax/bicg, integer 16×16) extend the evidence beyond hand-built
toys; **all three auto-derive their target via the Fix-3 probe** (gemm conservatively falls
back to baseline 2060; atax/bicg derive real targets — 280 and 162 — and optimize within a 2×
area cap). Head-to-head, recipe vs raw LLM under honest scoring (the four re-baselined LLM
arms):

| kernel | recipe arm | raw-LLM arm | winner |
| --- | --- | --- | --- |
| mac8_001 | interval 256 / LUT 315 | no improvement (full-unroll interval 3073 discarded) | **recipe** |
| matmul_001 | interval 44 / LUT 3121 *(satisfice, target 72)* | no improvement (no candidate meets target) | **recipe** |
| gemm_001 | no improvement (probe fallback, target 2060) | no improvement | tie (both null) |
| atax_001 | interval 64 / LUT 3907 / ADP 22.0 | interval 81 / LUT 3994 / ADP 28.0 | recipe (marginal) |

On structured-reduction kernels the raw LLM over-parallelizes and, under the corrected
scoring, **wins nothing**; the precise recipe applies the single unblocking pragma. On
kernels the safe recipes can't crack both are null; elsewhere they are comparable. The
`recipe`-before-`ollama` default is what captures the best of both. **Still pending:**
LLM-arm re-baselines for the remaining hand-built kernels; more PolyBench ports.

## 4. Budget-awareness discussion

The final stage is scored **80% performance / 20% innovation** (confirmed 2026-06-20
from the official FPT'26 page), with correctness a precondition for either — which is
exactly what HARPO optimizes for: a correctness-dominated score that then maximizes
PPA under a metered tool budget.

HARPO treats tool calls as the scarce resource the competition meters.
**Per-task budgets** are honored by `policy_allows` checking `can(action)` before every
csim/csynth/LLM call, with a held-back **reserve** so a winning candidate can always be
re-verified at the end. The demonstrated suite spent 42 tool calls and 2400 tokens total
— comfortably inside the per-task limits (csim 20, csynth 10, llm_calls 30). The budget
also encodes **don't-waste rules**: no csynth before csim passes (stage ordering), and no
fresh LLM call when the state is *repeated* or *regressed* (re-trying a failing fix burns
budget for nothing).

**Correctness before PPA** is structural, not advisory: the lexicographic score's top
term is the correctness tier, and the optimize loop re-verifies csim on every candidate
*before* reading its synthesis metrics, discarding any pragma that breaks behavior.

**The lexicographic objective — and its honest nuance.** Ranking II ahead of latency is
the right default for streamed/throughput kernels, but it can *raise single-call
latency*: on `matmul_001`, `latency_worst` rose 260→518 even as II improved 4→1, because
the loop greedily takes the initiation-interval win. The same ordering is what makes the
LLM's over-parallelization (§2) score "better" step-by-step. This argues for a
**per-task objective knob** (throughput- vs latency-oriented order) so latency-critical
kernels aren't penalized — listed in future work.

## 5. Reproducibility

Everything runs on **free, local** infrastructure at **$0 LLM cost**: the LLM is a local
**qwen** model served by Ollama over plain HTTP (endpoint/model from env
`HARPO_OLLAMA_URL` / `HARPO_OLLAMA_MODEL`); synthesis is **Vitis HLS 2025.2**,
free on Linux pre-2026.1 (GATE0.md), part `xc7z020clg400-1` (entry-level, free-tier
covered), 10 ns clock. The agent package is **stdlib-only**.

One-liners (from RESULTS.md / README.md):

```bash
source ~/tools/Xilinx/2025.2/Vitis/settings64.sh         # for any csynth/optimize/pipeline
python3 -m harpo repair   tasks/vadd_buggy_001 --provider mock,ollama
python3 -m harpo optimize tasks/mac8_001       --provider recipe,ollama
python3 -m harpo pipeline tasks/vadd_buggy_001                       # repair then optimize
python3 scripts/run_suite.py                              # aggregate runs/ -> SUITE.md + SUITE.csv

# the headline ablation:
python3 -m harpo optimize tasks/mac8_001 --provider recipe   # -> docs/ablations/mac8_001_recipe.json
python3 -m harpo optimize tasks/mac8_001 --provider ollama   # -> docs/ablations/mac8_001_ollama.json

# offline self-tests (no Vitis, no LLM):
python3 scripts/selftest.py            # parse_csim classification
python3 scripts/selftest_recipes.py    # RecipeProvider emits valid C++ (g++ -fsyntax-only)
python3 scripts/selftest_csynth.py     # parse_csynth resource-util% from stored XML
```

Every run writes replayable JSON under `runs/<task_id>/` (per-candidate `{csim,csynth}_
{raw,parsed}.json` + the phase log with budget, tokens, and per-candidate scores), so
every number in this paper is regenerable from a committed artifact.

> **Install gotcha (GATE0.md).** The unified Vitis 2025.2 installer omits the
> `bin/vitis_hls` launcher; recreate the loader wrapper or `vitis_hls` won't be on PATH
> even after sourcing `settings64.sh`.

## 6. Limitations and future work

**Implemented (was the top of this list; now code-complete + re-baselined, 106/106 tests green — §3.5/§3.6):**

- **Fix 1 — throughput scored on the design `interval_max`, not the per-loop II.** The
  old score's throughput term was the worst per-loop `PipelineII`; a *fully-unrolled* loop
  reports no II (`None`), which sorted as neutral and thus *beat* a real II≥1, so the loop
  **rewarded over-unrolling** (a re-ablation accepted a `mac8_001` design at **interval 3073,
  worse than baseline 1024**, §2, `recipe-vs-llm.md`). The scorer now uses `interval_max`,
  under which that design loses, and the old `conv2d_001` over-pragma'd candidate (interval
  328) loses to its baseline (191) — while the proper recipe now drives conv2d to interval 82
  under a target (§3.6). Per-loop `ii` is diagnostic-only.
- **Fix 2 — default objective is `satisfice_then_area`.** Area was the *last* lexicographic
  tiebreaker, so a genuinely-faster-but-huge LLM design (interval 128 / 13194 LUT) outranked
  the elegant recipe (256 / 315 LUT). The per-task objective is now a 5-value enum
  (`speed_first`/`area_first`/`adp`/`satisfice_then_area`/`pareto_report`; legacy
  `throughput`/`latency` alias to `speed_first`) defaulting to `satisfice_then_area`: meet a
  per-task `throughput_target`, then minimize the normalized `area_score` (`harpo/area.py`).
  Prompt hardening alone did **not** fix this (it's a scoring property, §2); the scoring
  fixes are the lever.
- **Fix 3 — autonomous target via a recipe-only capped probe (`harpo/probe.py`).**
  Removes the need for hand-written `throughput_target`s: a zero-token, capped, single-pragma,
  no-full-unroll probe derives the target (lowest `interval_max` within 2× baseline area, else
  baseline fallback). Derives `mac8`'s 256 autonomously; demonstrated on the PolyBench ports
  (§3.6), which ship with no hand-set target.

**Still pending / future work:**

- **Track-A task-type coverage (gated on the official harness).** HARPO currently
  proves optimize, csim-repair, and the full 6-step workflow; the remaining Track-A task
  types — synthesis-failure repair, cosim, streaming kernels, unified-credit budget mode,
  and the official eval-interface adapter — are designed but not yet buildable until the
  official evaluation harness is published. The honest map of what is proven vs. scoped is
  `docs/TRACK-A-COVERAGE.md`.
- **LLM-arm re-baseline breadth.** The recipe arm is re-baselined for all optimize kernels and
  the raw-LLM arm for mac8/matmul/gemm/atax (§3.6); the remaining hand-built kernels'
  LLM arms — `stencil3_001`, `unroll8_001`, `conv2d_001` — are still to run.
- **Recipe→LLM handoff (area-aware prompt shipped, insufficient alone).** The optimize prompt
  forbids stacking UNROLL on a pipelined loop and states an area ceiling; §2 shows the
  over-parallelization was driven by the *score*, so the scoring fixes above — not the prompt
  — are the durable fix.
- **Static/contract check in the repair loop.** Not yet built; repair is currently csim-based.
- **More kernels.** `matmul_001` (8×8) and `conv2d_001` extend coverage beyond 1-D reductions,
  and three **PolyBench ports — `gemm`/`atax`/`bicg` (integer 16×16)** now provide a
  standard-benchmark subset (§3.6). A longer FIR and larger matmul/conv remain optional breadth;
  per the project plan, benchmark count is deliberately capped here in favor of consolidating
  the ablation.
- **Suite-table latency column.** `run_suite.py` renders latency from `latency_best`
  while the per-task analysis uses `latency_worst`; align before camera-ready.

---

### TODO placeholders for the maintainer

- **§3.4 `conv2d_001` row** — all cells TODO. No committed phase log yet; HANDOVER.md
  flags conv2d as the next breadth kernel. (Also a longer FIR — `fir_001` exists as a
  fixture but has no committed phase log either.)
- No other fabricated numbers: every other quantitative claim is copied verbatim from
  RESULTS.md, recipe-vs-llm.md, GATE0.md, or the README results table.
- Optional alignment note (not a fabrication): RESULTS.md §5 caveat about the suite
  latency column (`latency_best` vs `latency_worst`) is carried into §6 for the
  maintainer to resolve before camera-ready.
