# Ablation: precise-pragma recipe vs. raw LLM on `mac8_001`

> **Read this first — historical discovery write-up.** This document is the
> *historical* deep-dive on the over-parallelization / scoring finding — the pre-fix
> origin of Fix 1 (`interval_max` metric) and Fix 2 (`satisfice_then_area` objective).
> The numbers in its tables are the **pre-fix** record, kept for the narrative.
> **Current numbers live in `docs/ablations/canonical/TABLE.md` (the single source of
> truth);** the canonical recipe-vs-LLM comparison *under the corrected scoring* is in
> `RESULTS.md`.

**What this captures.** The same `optimize` loop, the same kernel (`mac8_001`, a
windowed-sum ×8), the same starting point, driven by two different patch
*providers*: the deterministic precise-pragma **recipe** library
(`--provider recipe`) versus the raw local **LLM** (`--provider ollama`,
qwen3.6:35b-a3b, local Ollama). Both arms reach a high-throughput design; they
differ dramatically in **area**. This is the design rationale for shipping
`harpo/recipes.py` (and for the `recipe,ollama` default provider order):
precise deterministic pragmas first, the LLM only for the tail the catalogue
can't reach.

All numbers below are pulled directly from the two committed JSON logs in this
directory, produced with **Vitis HLS 2025.2**, part
`xc7z020-clg400-1`, 10.0 ns clock. Reproduce with:

```bash
source ~/tools/Xilinx/2025.2/Vitis/settings64.sh
python3 -m harpo optimize tasks/mac8_001 --provider recipe   # -> mac8_001_recipe.json
python3 -m harpo optimize tasks/mac8_001 --provider ollama   # -> mac8_001_ollama.json
```

## Result

| design | II | latency (worst) | interval | LUT | FF | DSP | Fmax (MHz) | tokens (P/C/total) | steps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **baseline** | 4 | 1026 | 1024 | 369 | 153 | 0 | 144.45 | — | — |
| **recipe-best** | **1** | **259** | 256 | **315** | 126 | 0 | 144.45 | 0 / 0 / **0** | 3 |
| **ollama-best** | n/a¹ | **129** | 128 | **13194** | 322 | 0 | 144.45 | 32747 / 1640 / **34387** | 6 |

¹ The LLM design fully **unrolls** the outer loop, so Vitis no longer reports a
per-iteration II for the original loop nest (`ii: null` in the log); throughput is
captured instead by the total **interval = 128** (vs. baseline 1024). It is a
genuine, correct throughput win — just paid for in area.

The baseline is identical across both arms (II=4, latency 1026, LUT 369), as
expected (same kernel, same csynth of the unmodified source).

## Exact pragmas each provider emitted

**Recipe (`mac8_001_recipe.json`, winner `cand_0001`)** — one fully specified
pragma:

```c
#pragma HLS ARRAY_PARTITION variable=in cyclic factor=8 dim=1
```

(The recipe also proposed `…on out` and `…factor=4 on in` as later candidates;
both were correctly discarded for no additional score gain.)

**LLM (`mac8_001_ollama.json`, winner `cand_0004`)** — a four-pragma stack:

```c
#pragma HLS ARRAY_PARTITION variable=in  cyclic factor=8 dim=1
#pragma HLS ARRAY_PARTITION variable=out cyclic factor=4 dim=1
#pragma HLS PIPELINE II=1
  ...
  #pragma HLS UNROLL factor=8        // inner loop
```

## Takeaway (precise, based on the actual numbers)

The recipe reaches **II=1 at LUT=315** with a single, surgically scoped pragma and
**zero LLM tokens**. The raw LLM reaches a comparable (in fact lower-latency:
129 vs 259) throughput design, but at **LUT=13194 — roughly 42× the recipe's
area** (and 36× the baseline's 369 LUT), while spending **34,387 tokens**. For an
xc7z020 (53,200 LUT) the recipe sits at 0.6% LUT utilization; the LLM design at
24%.

**Nuance vs. the original hypothesis — reported honestly.** The handover's prior
observation framed the LLM blow-up as an *imprecise* `ARRAY_PARTITION` (missing
the partition **type**) silently defaulting to `complete`. With the **current**
optimizer prompt (`_OLLAMA_OPT_SYSTEM_PROMPT`, which now explicitly forbids bare
`ARRAY_PARTITION` and warns that omitting the type "detonates area") the LLM no
longer makes that specific mistake — every partition it emitted here was a
fully-specified `cyclic factor=N`. The area blow-up reproduced anyway, but via a
**different** mechanism: the LLM piles on aggressive structural transforms —
`PIPELINE II=1` **plus** `UNROLL factor=8` on top of partitioning — fully
spatially unrolling the reduction. Each step strictly improves the lexicographic
score (II → latency dominate area), so the loop greedily accepts the
ever-larger-but-faster design. The recipe achieves the throughput target with
the minimal area-preserving move and stops.

So the lesson is the same one the recipe library was built to encode, just
sharpened: **a raw LLM is fluent but imprecise about *how hard to push* — it
over-applies parallelism for marginal latency at order-of-magnitude area cost,
whereas the deterministic recipe applies exactly the one pragma that unblocks
II=1 and no more.** This is precisely why the optimize default is `recipe,ollama`.

**Variance.** The LLM arm was run **3 times** (`mac8_001_ollama_run1.json`,
`_run2.json`, `_run3.json`). It was **highly stable**: all three runs converged on
the identical winning candidate (`cand_0004`), the identical four-pragma stack,
and the identical PPA (LUT 13194, latency_worst 129, FF 322, 34,387 tokens). Run 1
is kept as the canonical `mac8_001_ollama.json`. The big-area outcome is therefore
not a lucky/unlucky draw — it is the LLM's consistent behavior on this kernel
under the current prompt.

## Follow-up: the area blow-up is a SCORING problem, not a prompting one

After the above, the optimize prompt was hardened (`_OLLAMA_OPT_SYSTEM_PROMPT`:
"one pragma per turn", "do not UNROLL a loop already pipelined to II=1", an
explicit area ceiling). A re-ablation (`mac8_001_ollama_postprompt.json`) shows the
prompt **did not fix the blow-up — it got worse**:

| arm | per-loop II | interval | latency | LUT | FF |
| --- | --- | --- | --- | --- | --- |
| baseline | 4 | 1024 | 1026 | 369 | 153 |
| recipe | **1** | 256 | 259 | **315** | 126 |
| ollama (pre-prompt) | none | 128 | 129 | 13194 | 322 |
| ollama (post-prompt) | none | **3073** | 3072 | **38441** | 10753 |

The post-prompt design is **worse than the baseline on every real metric**
(interval 1024→3073, latency 1026→3072, LUT 369→38441) — yet the loop **accepted
it**. Root cause is the **score**, not the LLM: the throughput term is the worst
per-loop `PipelineII`, and a fully-unrolled loop reports **no** II (`None`). The
`neg()` helper sorts a missing metric as **0**, which *beats* the baseline's real
II=4 (−4). So the lexicographic score literally **rewards full spatial unrolling**
— the more the LLM unrolls, the more its II "disappears" and the better it scores,
regardless of interval/latency/area. The prompt can nudge the proposals; it cannot
override a score that prefers the blow-up.

**Fix — now IMPLEMENTED and re-baselined (code-complete, 106/106 tests green; see the
canonical table).** Both halves of the fix have landed and the recipe arm is
re-baselined on real Vitis; the corrected-scoring numbers are in
`docs/ablations/canonical/TABLE.md` (the numbers in the tables above remain the
**pre-fix** record):

1. **Metric:** throughput is now scored on the **design `interval_max`** (the honest
   throughput metric), not the per-loop II — under which the post-prompt design (3073)
   correctly *loses* to the baseline (1024), and `conv2d_001`'s pragma'd candidate (328)
   correctly loses to its baseline (191). Per-loop `ii` is diagnostic-only.
2. **Objective:** the per-task objective is now a 5-value enum with **`satisfice_then_area`
   as the default** (`speed_first`/`area_first`/`adp`/`satisfice_then_area`/`pareto_report`;
   legacy `throughput`/`latency` alias to `speed_first`). Backed by `harpo/area.py`
   (normalized `area_score` with no per-resource weights, `adp`, `resource_growth_ratio`,
   `pareto_front`) and a per-task `throughput_target` field. `interval_max` scoring alone
   does *not* stop a genuinely-faster-but-huge design from winning on throughput; only
   satisficing throughput to a target and then minimizing area makes the **elegant recipe
   (256 / 315 LUT) outrank the genuinely faster but huge LLM design (128 / 13194 LUT)**.

The prompt hardening is kept as good guidance but was **necessary-not-sufficient**; the
scoring fix was the real lever, and it is now in the codebase. The head-to-head above has
been **re-run under the corrected scoring** — those refreshed numbers and verdicts live in
the canonical table (`docs/ablations/canonical/TABLE.md`); under it, the recipe's
elegant `mac8_001` design wins and the full-unroll blow-up (interval 3073) is rejected.

## Reproducible evidence (files in this directory)

- `mac8_001_recipe.json` — the recipe arm (II=1, LUT=315, 0 tokens).
- `mac8_001_ollama.json` — the LLM arm, canonical (= run 1; LUT=13194, 34,387 tokens).
- `mac8_001_ollama_run1.json`, `mac8_001_ollama_run2.json`,
  `mac8_001_ollama_run3.json` — the three LLM repeats documenting the low variance.
- `mac8_001_ollama_postprompt.json` — the post-prompt re-ablation proving the
  blow-up is a scoring problem (accepted interval 3073 > baseline 1024).
- `matmul_001_optimize.json`, `conv2d_001_optimize.json` — generalization kernels.
