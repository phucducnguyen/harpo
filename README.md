# HARPO

A **budget-aware LLM agent for HLS** (AMD Vitis HLS) C/C++ that **repairs** broken
kernels to correctness and then **optimizes** their PPA (performance / power /
area) — under a *strict per-task tool-invocation budget*. The problem setting
follows the task formulation of the **FPT'26 AMD FPGA Design Competition, Track A
(LLM4HLS)**; HARPO was built independently against that formulation and is
released as standalone research (see `paper/`). The ranking rule is
**correctness before PPA**: a design must pass C-simulation before any
synthesis metric counts, and every optimization is kept only if it *re-verifies
correct* and *strictly improves* a correctness-dominated, objective-driven score.
HARPO is not "we used an LLM to write HLS code" — it is a closed control loop
(run tool → parse report → diagnose → propose one minimal change → verify →
keep/rollback) that spends its csim / csynth / LLM calls deliberately and leaves a
replayable evidence trail for the paper.

## Scoring — the 3-fix story

Throughput is scored on the design-level **`interval_max`**, not per-loop `ii`
(**Fix 1, metric**): a fully-unrolled loop reports `ii = None`, which used to sort
as 0 and spuriously reward over-unrolling — `interval_max` is always reported and
monotone, so `ii` is now diagnostic-only. Above that, a per-task **objective** enum
(`speed_first | area_first | adp | satisfice_then_area | pareto_report`, default
`satisfice_then_area`) picks the PPA ordering (**Fix 2, policy**): `satisfice_then_area`
meets a throughput target (an `interval_max` ceiling), *then* minimizes normalized
`area_score` (`area.py`), then ADP — so the agent doesn't blindly chase the fastest
design. When a task gives no target, a recipe-only, **0-token**, capped probe
(`probe.py`) derives one before the loop (**Fix 3, autonomy**). Correctness still
dominates everything: a csim+csynth pass always outranks a non-pass.

## Status

The agent is **complete**: the full closed-loop repair-then-optimize pipeline is
implemented, all **106 unit tests pass**, and the complete write-up lives in
**[`paper/`](paper/)**.

The toolchain was proven out first via two Gate-0 milestones — both pass on
**atlas** (Linux) with **Vitis HLS 2025.2** (free on Linux pre-2026.1):

- **Gate 0a — csim:** `gpp` backend (host g++) reproduces Vitis csim pass/fail
  with no Vitis needed (g++ ignores `#pragma HLS`).
- **Gate 0b — csynth/PPA:** real Vitis HLS 2025.2 via a generated tcl produces
  parsed latency / II / LUT / FF / BRAM / DSP.

Full detail, the verified tool config, and the **install gotcha** (the 2025.2
unified installer omits the `bin/vitis_hls` launcher — must be recreated) are in
**[GATE0.md](GATE0.md)**.

## Quick start

```bash
# csim works WITHOUT Vitis (g++ only) — repair + the correctness spine:
python3 scripts/selftest.py                                  # parser logic, offline (no compiler)
python3 -m harpo run    tasks/vadd_001       --stage csim    # -> pass
python3 -m harpo run    tasks/vadd_buggy_001 --stage csim    # -> functional_fail
python3 -m harpo repair tasks/vadd_buggy_001 --provider mock,ollama

# csynth + the optimize/pipeline loops need Vitis HLS on PATH:
source ~/tools/Xilinx/2025.2/Vitis/settings64.sh
python3 -m harpo run      tasks/vadd_001  --stage csynth --backend vitis_hls
python3 -m harpo optimize tasks/mac8_001  --provider recipe,ollama
python3 -m harpo pipeline tasks/vadd_buggy_001                 # repair, then optimize
```

**What success looks like.** Each subcommand prints a JSON summary and a one-line
verdict on stderr, and writes a log under `runs/<task>/`:

- `repair`   → `"repaired": true` once a forked candidate passes csim.
  (e.g. `vadd_buggy_001` is fixed in **2 steps / 1 LLM call** by the local model.)
- `optimize` → `"improved": true` when a kept candidate beats the baseline score.
  (e.g. `mac8_001` goes **interval_max 1024→256, latency 1026→259** under
  `satisfice_then_area`, at **0 LLM tokens**.)
- `pipeline` → `REPAIRED+IMPROVED` when both phases land, on one shared budget.

Exit codes: `0` = pass / repaired / improved · `1` = fail / not-repaired /
no-improvement · `2` = tool unavailable.

## Subcommands

| Command | What it does |
| --- | --- |
| `run <task> --stage {csim,csynth}` | Run **one** stage once; print the parsed report; write evidence. |
| `repair <task>` | Closed-loop **correctness** repair: csim → diagnose → patch → re-csim, under budget. |
| `optimize <task>` | **PPA** loop on an already-correct design: propose pragma → re-verify csim → csynth → keep iff score improves. |
| `pipeline <task>` | `repair` then (only if repaired) `optimize`, sharing **one** per-task tool budget. |

## Backends and providers

**Backends** (the tool runner — `--backend` / `--csim-backend` / `--synth-backend`):

- `gpp` — host C++ compile + run = functional **csim** equivalent. Works with no
  Vitis. Cannot do csynth/PPA and won't catch non-synthesizable constructs
  (recursion, malloc, unsupported STL) — those need the real tool.
- `vitis_hls` — real Vitis HLS flow (csim + csynth) via a generated `run_harpo.tcl`.
  Part / clock / source list are **injected from the task**, never hardcoded.

**Providers** (who proposes a patch — `--provider`, comma-separated, tried in order):

- `mock` — deterministic string-replacement patcher (tests/demo; reads optional
  `mock_patch.json` from the task dir). No external services, no tokens.
- `recipe` — deterministic, non-LLM **optimization** library of *precise*,
  correct-by-construction HLS pragmas (e.g. `ARRAY_PARTITION cyclic factor=8 dim=1`),
  emitted one at a time. No tokens.
- `ollama` — best-effort LLM patcher over a **local** Ollama server (stdlib
  `urllib` only; never raises — degrades to the next provider on any failure).
  Endpoint/model come from env: **`HARPO_OLLAMA_URL`** and
  **`HARPO_OLLAMA_MODEL`**. Repair defaults to `mock,ollama`; optimize defaults
  to `recipe,ollama` (precise recipes first, LLM for the tail).

## Evidence and the canonical table

Every run writes replayable JSON under `runs/<task_id>/`:

- `runs/<task>/<cand>/{csim,csynth}_{raw,parsed}.json` — per-candidate tool output + parse.
- `runs/<task>/{repair,optimize,pipeline}_log.json` — the full event trail, budget
  spent, token account, and per-candidate scores for one phase.

The **single source of truth for results is
[`docs/ablations/canonical/TABLE.md`](docs/ablations/canonical/TABLE.md)** —
one row per kernel × method (baseline / recipe / raw-LLM), with `interval_max`,
latency, LUT/FF/BRAM/DSP, `area_score`, ADP, tool calls, tokens, and the
accept/reject reason. Regenerate it (and the optional Pareto/ADRS view) from the
run logs:

```bash
python3 scripts/run_ablation.py            # (re-)run the kernels (needs Vitis), write per-arm JSON
python3 scripts/ablation_table.py          # JSON -> docs/ablations/canonical/TABLE.md (+ .csv)
python3 scripts/pareto_view.py             # optional -> docs/ablations/canonical/PARETO.md
```

## Results

Proven on **atlas**, real **Vitis HLS 2025.2**. Full numbers live in
[`docs/ablations/canonical/TABLE.md`](docs/ablations/canonical/TABLE.md); the
recipe-vs-LLM area lesson is in **[docs/RESULTS.md](docs/RESULTS.md)**. Highlights:

- **8 kernels** — 5 hand-built (`mac8_001`, `stencil3_001`, `unroll8_001`,
  `matmul_001`, `conv2d_001`) + 3 PolyBench ports (`gemm_001`, `atax_001`,
  `bicg_001`, integer 16×16) — plus repair fixtures (`vadd_buggy_001`, …).
- Under `satisfice_then_area`, the deterministic **recipe** provider meets the
  throughput target at **0 LLM tokens** and decisively beats the raw LLM on the
  over-parallelizing kernels (e.g. `mac8_001` `interval_max 1024→256`,
  `matmul_001 256→44`), where the raw LLM keeps the baseline.
- On the kernels where a target is auto-derived (`atax_001`, `bicg_001`), the
  `probe.py` probe supplies the ceiling at 0 tokens before the loop runs.

**106 unit tests green:** `python3 -m unittest discover -s tests`.

## How it works (short version)

The control loop, candidate isolation, budget policy, the objective-driven
correctness-dominated score (throughput on `interval_max`, `satisfice_then_area`
default + target probe), the correctness-preserving invariant, and the provider
protocol (so you can add a provider) are documented in
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Tasks are dev fixtures, not the competition's

The competition supplies its own task bundles (kernel, target part, tool version,
budget config). The kernels under `tasks/` are dev fixtures; the runner takes
part / clock / tool / budget as **injected config** (`spec.json`,
`constraints.json`, `budget.json`), never hardcoded — so the same agent runs the
evaluator's tasks unchanged.

## Layout

```
harpo/        Python package (stdlib only):
  task.py         load a task bundle -> TaskContext
  runner.py       backends: gpp (g++ csim) | vitis_hls (real csim+csynth via tcl)
  parser.py       parse_csim / parse_csynth (Vitis XML -> metrics)
  diagnosis.py    parser status -> Diagnosis (rule-based, deterministic)
  patch_engine.py PatchProvider protocol; MockProvider, OllamaProvider; check_contract, apply_patch
  recipes.py      RecipeProvider + the precise-pragma catalogue
  candidate.py    CandidateManager (isolated src copies) + score()/best()/pareto_front()
  area.py         area_score (normalized utilization) + adp (area-delay product)
  probe.py        recipe-only 0-token throughput-target probe (when none given)
  budget.py       BudgetManager + policy_allows (the Track-A spine)
  agent.py        run_repair / run_optimize / run_pipeline
  store.py        per-run JSON evidence
  cli.py          run / repair / optimize / pipeline
scripts/          selftest.py (csim parser), selftest_recipes.py (recipe g++ check),
                  selftest_csynth.py (csynth parser), run_suite.py (evidence aggregator),
                  run_ablation.py + ablation_table.py (canonical TABLE.md), pareto_view.py
tasks/            dev fixtures: 5 hand-built (mac8, stencil3, unroll8, matmul, conv2d)
                  + 3 PolyBench (gemm, atax, bicg) + repair fixtures (vadd*, scale*)
runs/             per-candidate run artifacts + phase logs
GATE0.md          toolchain gates (0a csim / 0b csynth) — PASSED
docs/             ARCHITECTURE.md, RESULTS.md, ablations/canonical/TABLE.md (source of truth)
```

## Origin of the problem setting

The task formulation — budgeted LLM4HLS with a correctness-dominated ranking rule —
comes from the **FPT'26 AMD FPGA Design Competition, Track A (LLM4HLS)**
(`fpt2026.uark.edu/fpt26-design-competition`). HARPO was built independently
against that formulation and is released as standalone research; it was not entered
into the competition. An honest map of what HARPO covers of the Track-A task
taxonomy (proven / partial / gap, verified against the code) is in
**[docs/TRACK-A-COVERAGE.md](docs/TRACK-A-COVERAGE.md)**.

## Paper

The preprint source lives in [`paper/`](paper/) (IEEE two-column; build
instructions in [paper/README.md](paper/README.md)). Every quantitative claim in it
traces to [docs/ablations/canonical/TABLE.md](docs/ablations/canonical/TABLE.md).

## License

MIT — see [LICENSE](LICENSE).
