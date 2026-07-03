# HARPO — Track A coverage map

*How HARPO's demonstrated capability lines up with the official FPT'26 Track A
specification.* Honest by design: ✅ proven, ⚠️ path exists but unproven, ❌ gap.

Source of the official requirements: the FPT'26 Track A description
(`fpt2026.uark.edu/fpt26-design-competition`, read 2026-06-20). Coverage claims below were
checked against the code (`harpo/`), not memory. Numbers/proofs trace to
`docs/RESULTS.md` and `docs/ablations/canonical/TABLE.md`.

## The bottom line

HARPO proves the **complete required agent workflow** on the two most central task
types — *optimize a correct-but-unoptimized baseline* and *repair a csim failure* — with the
diagnosis/budget architecture already reaching toward the others. The remaining items are a
**scoping list gated on the official evaluation harness**, which has not been published yet
("submission portal + FAQ announced in due course"). Several of them **cannot be built
correctly until that harness drops** — building now means guessing the interface and risks
rework. This is why the engineering freeze still holds.

## 1. Task initial conditions (judges may send any of these)

| Official task type | HARPO mechanism | Status |
| --- | --- | --- |
| Functionally correct but **unoptimized** baseline | `run_optimize` (8 hand-built + 3 PolyBench kernels) | ✅ **proven** |
| **Fails compilation** | `parser` → `compile_error`; `diagnosis` → `minimal_compile_fix`; repair loop drives it | ⚠️ path exists; **no fixture proves it** (repair fixtures are functional bugs, not compile failures) |
| **Fails synthesis** | `SYNTHESIS_FAIL` diagnosis class + `parse_csynth`, but `run_repair` runs the **csim (gpp) stage only** | ❌ **gap** — a design that passes csim yet fails csynth is not driven by any repair loop |
| Compiles but **fails csim** | `run_repair` (vadd_buggy / offbyone / scale_wrongop) | ✅ **proven** |
| Compiles but **fails cosim** | cosim is budgeted + stage-gated, but `runner` marks it "(later)" | ❌ **cosim not implemented** |
| Compiles but fails **hidden functional tests** | agent runs the *provided* testbench; hidden tests are judge-side | ✅ (by design — nothing to build) |
| **Structural: severe resource inefficiency** | `run_optimize` + `RESOURCE_OVERUSE` | ✅ proven |
| **Structural: deadlock** | `TIMEOUT_OR_DEADLOCK` class + csim timeout detection | ⚠️ class exists; **no streaming/dataflow kernel demonstrated** |
| **Structural: invalid streaming behavior** | — (no `hls::stream`/dataflow kernel in the task set) | ❌ **gap** |
| Other HLS compilation problems | catch-all via the `compile_error` path | ⚠️ partial |

## 2. Required agent workflow (the 6 steps) — fully covered

| Required step | HARPO | Status |
| --- | --- | --- |
| 1. Interpret the task spec + initial code | `task.py` → `TaskContext` (part/clock/sources/policy/budget injected) | ✅ |
| 2. Generate/modify HLS C/C++ incl. pragmas | `recipes.py` (deterministic) + `patch_engine.py` (LLM) | ✅ |
| 3. Invoke tool feedback interfaces | `runner.py` (gpp csim, vitis_hls csynth) | ✅ |
| 4. Parse logs/reports for diagnosis | `parser.py` + `diagnosis.py` | ✅ |
| 5. Correctness before PPA | structural invariant: every candidate re-runs csim *before* its csynth metrics are read; correctness tier dominates the score | ✅ |
| 6. Terminate within budget | `budget.py` (`policy_allows` checks `can()` before every call; reserve held for final verify) | ✅ |

This row block is HARPO's strongest alignment — it was built around exactly this loop.

## 3. Provided task artifacts the agent must consume

| Artifact | HARPO | Status |
| --- | --- | --- |
| Source files (baseline C/C++) | injected via `TaskContext` | ✅ |
| Testbench + **build scripts (e.g. Makefile)** | HARPO uses its **own** runner/tcl, not a provided Makefile | ⚠️ **adapter likely needed** to the evaluator's build/run interface |
| Spec: interface contract, data types | `spec.json` carries interface/types | ✅ |
| Spec: **numerical tolerance** | csim compare is exact today | ⚠️ tolerance-aware compare may be needed |
| Spec: design constraints | spec/constraints JSON | ✅ |
| Target constraints (part/clock/optional resource limits) | injected; `RESOURCE_OVERUSE` handles limits | ✅ |
| **Budget config** — max csim/cosim/synth **OR a unified credit budget** | `BudgetManager` is **per-tool only** (the `mode` key exists but `can()` never branches on it) | ❌ **unified-credit mode not implemented** |

## 4. The #1 integration risk (unknowable today)

The spec requires the agent to **"invoke the *provided* evaluation interfaces."** The
competition will ship its own evaluation harness/interface — *not yet published*. HARPO
calls Vitis directly through its own `runner`. **An adapter from HARPO's runner to the
official interface will almost certainly be required, and it cannot be written correctly
until the harness is released.** This is the single biggest integration unknown and the main
reason to keep engineering frozen until the harness drops.

## 5. Post-harness scoping list (do NOT start before the official harness + a decision to unfreeze)

In rough priority order once the evaluation interface is published:
1. **Eval-interface adapter** — wrap `runner` to call the official csim/cosim/synth
   interfaces and consume the provided Makefile/build scripts. (#1 risk; harness-gated.)
2. **Unified-credit budget mode** — branch `BudgetManager.can()` on `mode` so a single credit
   pool is honored, if that's what the evaluator meters.
3. **Synthesis-failure repair** — drive `run_repair` (or a unified repair stage) from
   `SYNTHESIS_FAIL`/`TIMING_FAIL`, not csim only.
4. **cosim stage** — implement the cosim backend the budget already reserves for.
5. **Streaming/dataflow kernels** — add an `hls::stream` task to exercise
   deadlock/invalid-streaming repair (`TIMEOUT_OR_DEADLOCK`).
6. **Numerical-tolerance compare** — honor a spec-declared tolerance in csim checking.
7. **Compile-failure fixture** — a fixture that proves the `compile_error` →
   `minimal_compile_fix` path end-to-end.

None of these change the current paper's claims, which are scoped to what is proven.
The paper should state coverage honestly and point here.
