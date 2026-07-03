# HARPO — Architecture

HARPO is a closed-loop HLS agent: it runs a tool, parses the report,
diagnoses the result, asks a provider for **one** minimal change, applies it to an
**isolated** candidate, verifies, and keeps the change only if it strictly helps —
all under a **per-task tool-invocation budget**. This document maps the modules,
shows the data flow for both loops, and explains the four ideas that make it a
Track-A agent rather than a one-shot LLM: candidate isolation, the budget policy,
the objective-driven correctness-dominated score, and the correctness-preserving
invariant.

## Module map

| Module | Role |
| --- | --- |
| `task.py` | `load_task()` normalizes a bundle dir (`spec.json` + `constraints.json` + `budget.json`) into one `TaskContext` (top function, src/tb file lists, part, clock, policy, budget). Tolerant of extra/missing fields — the evaluator supplies its own. |
| `runner.py` | The **Tool Flow**. `run_stage(task, stage, out_dir, backend)` dispatches to a backend: `gpp` (host g++ compile+run = csim) or `vitis_hls` (real csim+csynth via a generated `run_harpo.tcl`). Part/clock/sources are injected from the task. Returns a raw dict. |
| `parser.py` | The **Report Parser**. `parse_csim()` → status `{pass, compile_error, functional_fail, timeout, tool_unavailable}`. `parse_csynth()` → metrics from the Vitis XML (II, depth, latency best/worst, Fmax, LUT/FF/DSP/BRAM + util%), plus timing/resource `violations` → status `{pass, timing_fail, resource_overuse, synthesis_fail, report_missing, tool_unavailable}`. |
| `diagnosis.py` | The **Diagnosis Engine**. Rule-based, deterministic (no model). `diagnose()` maps a csim status → `Diagnosis(klass, recommended_action, evidence, repeated)`; `diagnose_csynth()` maps a csynth status → a Diagnosis whose `recommended_action` is `optimize_ppa` for a clean/improvable pass. A repeated failure klass escalates to `rollback_or_escalate`. |
| `patch_engine.py` | The **Patch Engine**: the `PatchProvider` protocol, `MockProvider` (deterministic string edits) and `OllamaProvider` (local LLM, stdlib urllib, never raises). Plus `check_contract()` (interface/edit-policy gate) and `apply_patch()` (writes into the candidate's own src copy; whole-file preferred, unified-diff fallback). |
| `recipes.py` | `RecipeProvider` + the precise-pragma catalogue: a deterministic, **non-LLM** optimization provider that emits well-formed pragmas (`ARRAY_PARTITION cyclic factor=N dim=1`, `PIPELINE II=1`, `UNROLL factor=N`, …) one per call, by robust text scanning. No tokens. |
| `candidate.py` | The **Candidate Store** front end: `CandidateManager` mints/forks candidates, each with an isolated editable `src/` copy; `task_view()` repoints a `TaskContext` at that copy. `score()` computes the correctness-dominated, objective-driven score (throughput on `interval_max`); `best()` picks the winner; `pareto_front()` returns the non-dominated `(interval_max, area_score)` set for `pareto_report`. |
| `area.py` | **Area metrics** (no model). `area_score()` = normalized utilization, the sum of (used / available) over LUT/FF/DSP/BRAM/URAM (no per-resource weights — dividing by each device capacity already lets scarce resources dominate). `adp()` = `area_score × interval_max` (area-delay product). Defensive: missing keys degrade to `None`, never raise. |
| `probe.py` | The **throughput-target probe**. When a task has no `throughput_target`, `derive_throughput_target()` runs a recipe-only (**0-token**), capped (≤4 single-pragma synths, **full-unroll excluded**) probe and `select_target()` picks the lowest `interval_max` within 2× baseline area (else falls back to the baseline interval). Runs once before the optimize loop; never raises. |
| `budget.py` | The **Budget Policy** — the Track-A spine. `BudgetManager` accounts tool calls, holds a reserve for final verification, and `policy_allows()` encodes the decision rules (no csynth before csim passes; stop on repeat/regress). |
| `agent.py` | The control loop: `run_repair()`, `run_optimize()`, `run_pipeline()`. Drives the cycle, records every step as a replayable event, writes `runs/<task>/{repair,optimize,pipeline}_log.json`. |
| `store.py` | Persists each run's raw + parsed JSON under `runs/<task_id>/<candidate_id>/` (stage-prefixed for multi-stage candidates). |
| `models.py` | Shared dataclasses/contracts: `Diagnosis`, `PatchProposal`, `ApplyResult`, `Candidate`, plus the `DIAGNOSIS_CLASSES` / `ACTIONS` enums. |
| `cli.py` | Argparse front door: `run` / `repair` / `optimize` / `pipeline`; builds the provider list (`mock` / `recipe` / `ollama`). |

## Data flow — repair loop (`run_repair`)

Drives **correctness** under the `BudgetManager`. Each iteration:

```
            ┌──────────────────────── budget.policy_allows("csim") ?
            │                                  │ no -> stop (record reason)
            ▼ yes
   ┌─> run_stage(csim, gpp) ──> parse_csim ──> store evidence
   │        │
   │        ▼
   │   diagnose(parsed, history)
   │        │
   │   csim PASS? ── yes ──> record success, winner = this candidate ──> DONE
   │        │ no
   │        ▼
   │   budget.policy_allows("llm_calls", regressed?, repeated?) ?
   │        │ no -> stop (repeat/regress or budget)
   │        ▼ yes
   │   for prov in providers:  proposal = prov.propose(view, sources, diag, history)
   │        │                  (accumulate prov.last_usage tokens)
   │        ▼
   │   check_contract(proposal)         # reject signature/testbench/glob violations
   │        │ ok
   │        ▼
   │   child = cm.fork(cand); apply_patch(child.src_dir, proposal)
   └────────┘   (cand <- child; loop)

   stop when: csim passes · max_steps · budget.exhausted() · contract reject ·
              apply fail · no provider produced a patch
   winner = best(all candidates)   # correctness-dominated; a csim-pass beats any fail
```

## Data flow — optimize loop (`run_optimize`)

Drives **PPA** on an already-correct design, **never breaking correctness**:

```
   baseline: run_csim (must PASS) ──> if fail: stop ("run repair first")
        │
        ▼
   baseline: policy_allows("csynth", csim_pass=True) ──> run_csynth ──> baseline_metrics
        │
        ▼  ★ TARGET PROBE (only when the task gives no throughput_target):
   derive_throughput_target(task)             # probe.py — recipe-only, 0 tokens
        │   capped ≤4 single-pragma synths, full-unroll EXCLUDED, fresh forks
        │   target = lowest interval_max within 2× baseline area, else baseline iv
        ▼  loop while step < max_steps and no_improve < patience:
   diagnose_csynth(cur_cs, history)            # recommended_action = optimize_ppa
        │   (feed back "already tried, no improvement" knobs so it diversifies)
        ▼
   proposal = provider.propose(...)            # recipe first, then ollama
        │
   check_contract(proposal) ── reject ──> tried+= ; no_improve+=1 ; continue
        │ ok
        ▼
   child = fork(best_cand); apply_patch(child)
        │
        ▼  ★ INVARIANT: re-verify correctness BEFORE trusting metrics
   run_csim(child) ── csim BROKE ──> discard child ; tried+= ; no_improve+=1 ; continue
        │ still PASS
        ▼
   policy_allows("csynth") ──> run_csynth(child)
        │
        ▼
   score(child) > score(best_cand) ?
        │ yes -> ACCEPT: best_cand = child ; cur_cs = child_cs ; no_improve = 0
        │ no  -> REJECT (no PPA gain): tried+= ; no_improve+=1
        ▼
   (repeat)
   result.improved = winner is a descendant that beat candidate[0] on score
```

`run_pipeline` chains the two: `run_repair`, then (only if repaired) `run_optimize`
seeded with the repaired winner's source (`seed_src_dir`), threading **one**
shared `BudgetManager` so both phases debit the same per-task account.

## Candidate-isolation model

Patches never mutate the original task bundle. `CandidateManager.create_initial()`
copies the task's source files into `runs/<task>/cand_0000/src/`; `fork(parent, id)`
copies the *parent's current edited* source into a fresh candidate dir.
`task_view(cand)` returns a `TaskContext` with `src_dir`/`src_files` repointed at
that candidate's editable copy while `tb_files` keep their original paths — so the
runner compiles the edited kernel against the **un-edited** testbench. Each attempt
is therefore a fully isolated, replayable artifact; the loop advances by forking,
and the winner is whichever candidate scores highest.

## Budget policy (the Track-A spine)

`BudgetManager` is constructed from the task's `budget.json`:

```json
{"mode": "per_tool",
 "limits": {"static_check": 100, "csim": 20, "csynth": 10, "cosim": 5, "llm_calls": 30},
 "reserve": {"final_csim": 1, "final_csynth": 1, "final_cosim": 1}}
```

- A **missing limit is unlimited** (`inf`).
- `can(action)` is true only while `spent < limit − reserve` — the **reserve** is
  held back so a winning candidate can always be re-verified at the end.
- `policy_allows(action, *, csim_pass, regressed, repeated)` enforces, in order:
  1. budget first (`can`);
  2. **stage ordering** — no `csynth`/`cosim` before csim passes;
  3. **stop/rollback guard** — refuse another `llm_calls` when the state is
     `repeated` or `regressed` (re-trying a failing fix is wasted budget).
- `exhausted()` = no csim and no llm calls left → the loop halts.

## The score (`candidate.score`)

The score is a sortable tuple, **correctness-dominated** and **objective-driven**.
Higher = better; lower-is-better metrics are negated, missing metrics sort as 0.
Two terms are fixed at the ends of every tuple:

1. **correctness tier** (first, always wins) — `0` csim unknown/fail, `1` csim
   pass, `2` csim+csynth pass. A tier-2 candidate always outranks a tier-1 one
   regardless of PPA — the structural "correctness before PPA" guarantee.
2. *(PPA terms — selected by the objective, see below)*
3. **fewer steps** (last tiebreak) — `-len(diagnosis_history)`, prefer the simpler fix.

**Throughput is scored on `interval_max`, the design-level initiation interval —
NOT per-loop `ii`.** A fully-unrolled loop reports `ii = None`, which would sort
as 0 and *spuriously beat* a real `ii ≥ 1` (rewarding over-unrolling, e.g.
`interval_max 3073` beating a `1024` baseline). `interval_max` is always reported
and monotone, so it avoids that trap; per-loop `ii` is kept in the metrics as
**diagnostic data only** and is never the primary throughput term.

The middle PPA terms come from a per-task **objective**, a 5-value enum in
`spec.json` (default `satisfice_then_area`; absent/unknown → default; legacy
`throughput`/`latency` alias to `speed_first`):

| objective | PPA ordering (within a correctness tier) |
| --- | --- |
| `speed_first` | `interval_max`, then worst-case latency, then `area_score` |
| `area_first` | `area_score`, then `interval_max` |
| `adp` | area-delay product (`adp`), then `area_score` |
| **`satisfice_then_area`** (default) | meet the throughput target, then minimize `area_score`, then ADP |
| `pareto_report` | same ranking as `satisfice_then_area`; also reports the `pareto_front()` |

**`satisfice_then_area`** is the default and the core policy: a candidate that
**meets the throughput target** (`interval_max ≤ throughput_target`) ranks above
any that misses it, and among those that meet it the winner is the one with the
smallest normalized `area_score` (ADP breaks further ties). Candidates that miss
the target are driven on throughput first. With no usable target (none set and
the probe could not derive one) it degrades to a speed-first ordering with an
area tiebreak — which is exactly why the **target probe** above runs first, so a
real target almost always exists. `throughput_target` is an `interval_max`
ceiling: hand-set in `spec.json`, or auto-derived by `probe.py`.

## The correctness-preserving invariant

An optimization is **accepted only if it (a) still passes csim AND (b) strictly
improves the score.** In `run_optimize`, every forked candidate is **re-run
through csim before its csynth metrics are even read** — if the pragma broke
functional behavior, the candidate is discarded and its metrics are never trusted.
This is the structural guarantee behind Track A's "correctness before PPA": the
agent can never trade a wrong-but-fast design up the ranking.

## The provider protocol — adding a new patcher

A provider is any object matching `PatchProvider` (`patch_engine.py`):

```python
def propose(self, task, sources: dict[str, str],
            diagnosis: Diagnosis, history: list[str]) -> PatchProposal | None: ...
# plus an attribute:  self.last_usage: dict | None   # token usage, or None
```

- `sources` maps each filename (relative to the candidate src dir) → its full text.
- Return a `PatchProposal(target_file, edit_plan, whole_file=..., expected_effect,
  risk_tags)` — prefer `whole_file` (robust; `apply_patch` also supports a unified
  diff fallback) — or `None` to abstain (the loop falls through to the next provider).
- Set `self.last_usage = {"prompt_tokens", "completion_tokens", "total_tokens"}`
  (or `None` for token-free providers) so the agent can account tokens.
- Read `diagnosis.recommended_action` to decide whether to fire: `RecipeProvider`
  only contributes when it is `optimize_ppa`; a repair provider acts on the
  correctness classes. Providers must **not** raise — degrade to `None`.

To add one (e.g. a remote model, a static-analysis fixer, a DSE engine): implement
`propose` + `last_usage`, register a name in `cli._build_providers`, and place it in
the `--provider` order. No change to the loop, the budget, or the score is needed —
the agent talks only to the protocol.
