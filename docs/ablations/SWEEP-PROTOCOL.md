# Variance sweep — protocol, frozen before the data

**Status: FROZEN 2026-08-15, committed before any sweep result was opened.**
A specification that can be edited after the data lands is not a specification. This file
is committed first precisely so the analysis cannot be tuned to the outcome. If it is
amended later, the amendment must be a separate dated commit that says what changed and
why — never an edit that makes this read as though it always said the new thing.

## Why this sweep exists

Every recipe-vs-LLM comparison published so far rests on **one run per arm**. A repeat run
of `mac8_001` contradicted the committed record: the canonical raw-LLM row reports "no
improvement, baseline kept" (interval 1024 / LUT 369) while a fresh run under the same
model reached interval 256 / LUT 315 — the design the recipe arm produces. One run is not
evidence of an arm's behaviour when the arm is not reproducible.

Related and already known: `docs/ablations/mac8_001_ollama.json` and its `_run1/2/3`
siblings are **byte-identical** (md5 `29f1d780463471d407aefe7dd719896d`) — one record
copied, not three runs. Any wording implying repeat sampling from those files is wrong.

## Design

5 passes × {recipe, llm} × {`mac8_001`, `matmul_001`, `atax_001`, `gemm_001`} = 40 arms.
Each pass's result JSON is copied out immediately to `<kernel>__<arm>__pass<N>.json`;
`runs/<task>/` is a fixed, gitignored path that every pass overwrites, so an uncopied pass
would vanish **without an error** and a 4-run cell would look identical to a 5-run cell.

The **recipe arm is the determinism control**, not filler. It is deterministic by
construction, so five bit-identical results establish the measurement floor for the whole
evidence base. Without it, no LLM-arm spread is attributable — you cannot call the model
unstable without first checking the pipeline.

## Endpoints — locked, no post-hoc redefinition

| ID | Endpoint | Definition frozen at `ae0632c` |
|---|---|---|
| P1 (primary, binary) | `improved` | The `improved` field as computed by the optimize loop at `ae0632c`. Not "it reduced LUT". Not re-scored under another objective. Not with an adjusted `throughput_target`. |
| P2 (secondary) | QoR | `interval_max`, `latency_worst`, `lut`, `ff`, `dsp`, `area_score`, `adp` — **all reported for every run**, so no metric can be *selected* after the fact because it flatters. |
| P3 (categorical) | winning pragma | The accepted candidate's `edit_plan`, classified into a vocabulary fixed now: PIPELINE-inner · PIPELINE-outer · UNROLL-full · UNROLL-factor · ARRAY_PARTITION-cyclic · ARRAY_PARTITION-block · ARRAY_PARTITION-complete · DATAFLOW · other · none. |
| P4 (cost) | budget | `tokens.total_tokens`, csim count, csynth count, `steps`. |

**Failure handling, pre-committed:** a run that errors (Vitis crash, Ollama timeout,
budget exhausted before any csynth) is recorded as `no_candidate_synthesized`, **counted in
the denominator, never re-run, never dropped**. No run is repeated until it agrees with
anything. If a pass is lost, `n` for that cell drops and the loss is stated in the header.

## Reporting rules

- **The per-run table is the result.** At n=5 the raw data is smaller than most summaries
  of it and strictly more informative. Everything else must be recomputable from it.
- **Success rate as k/5 with an exact Clopper–Pearson 95% interval**, reported with its
  plain-language limit in the same sentence. ⚠️ Five successes out of five do not exclude a
  true rate of 48% (CP 95% = [0.478, 1.000]). If that sentence is uncomfortable, the answer
  is more runs, not softer wording.
- **Median + observed min–max** for QoR, conditional on success, labelled verbatim as
  "observed range, not a confidence interval".
- **Distinct-outcome count** for the LLM arm ("3 distinct designs in 5 runs") — a count,
  requiring no distributional assumption.
- **Per kernel, never pooled.** Cross-kernel statements are counts ("unstable on 2 of 4"),
  never an average over 20 runs.

## Explicitly NOT reported, and why

- **Mean ± sd.** The outcome is bimodal by construction — an arm either finds the
  unblocking pragma or does not. A 3/5 mac8 outcome gives LUT {315,315,315,369,369}, mean
  **336.6: a design no run produced and that does not exist.** The median, 315, is real.
- **Any "95% CI" on a QoR number.** There is no defensible sampling model for LUT counts
  here. The string "95% CI" may appear only next to a Clopper–Pearson interval on a
  proportion.
- **Quartiles/IQR, standard error, CV.** At n=5 the quartiles are not identified.
- **Significance tests, in the body.** At 5v5 Mann–Whitney's minimum attainable two-sided
  p is 0.0079, so only complete separation can ever clear 0.05; Fisher on P1 gives 5/5 vs
  2/5 → p = 0.167. Anything short of near-total separation is "non-significant" *by design
  of the sample size*, and printing that invites a reader to hear "no difference". The four
  relevant p-values go in an appendix footnote answering the anticipated question, and
  nowhere else.
- **Best-of-5 as an arm's result.** That is max-selection bias — the same error that
  produced the current headline from a single run, with more chances to make it.

## Vocabulary rules

- *deterministic*, *stable*, *reproducible* are reserved for the **recipe** arm.
- The LLM arm gets "temperature 0 (greedy), which is **not** run-to-run deterministic in
  this setting". ⚠️ `patch_engine.py` sends `temperature: 0` and **no seed and no pinned
  `num_ctx`**. Greedy decoding is deterministic only given identical logits, and logits
  move with server batch composition, KV-cache reuse, context state, GPU reduction order,
  and quantization/offload split under VRAM pressure — this host shares the GPU with
  another always-on service. The agent loop compounds it: each prompt embeds prior-iteration
  history, so one divergent token changes every later call.
- Banned without an adjacent literal count: repeatedly · consistently · always · never ·
  stable · robust · reliably · in general. Every claim carries "in 5 runs" and the dates.
- **"wins nothing" is deleted everywhere.** It is an existential claim; no sample size
  supports it.

## The previously published run is not a sixth sample

The canonical rows are **superseded, not a tiebreaker**. They are from a different date and
carry no `model` field, so what produced them is unrecorded. They appear in a separate row
labelled "previously published single run", and the reader sees whether it falls inside the
observed range. That handling doubles as the erratum documentation.

## Environment, captured at freeze time

```
host          atlas (Vitis HLS 2025.2, part xc7z020clg400-1, 10 ns clock)
model         qwen3.6:35b-a3b-q4_K_M
digest        sha256:07d35212591fc27746f0a317c975a6d68754fb38e9053d82e25f06057af28522
size on disk  23,938,333,577 B      resident 27,141,657,728 B (fully in VRAM)
quantization  Q4_K_M, parameter_size 36.0B, family qwen35moe
code          ae0632c
sweep started 2026-08-15T23:02:50-07:00
```

⚠️ The GPU is shared with an always-on knowledge service that runs scheduled jobs overnight.
If the sweep crosses those windows, model residency or offload split can change mid-sweep.
That is a legitimate variance source; if it is not logged, it is stated as a limitation
rather than assumed away.

## Deposit handling

The v1 preprint is deposited (Zenodo `10.5281/zenodo.21366536`). Mismatches are erratum or
revision candidates — **never silent edits to the deposit**. Two items are now on that list:
the "wins nothing" claim, and any wording implying the `_run1/2/3` files were repeat runs.
Both are corrections of substance, so the revision must say what was wrong and why, not
merely restate a new number.
