# LLM-for-HLS Prior Art: How the Field Evaluates & Selects Designs

Research date: 2026-06-15. Purpose: ground HARPO's candidate-selection objective
(how to rank a *correct* design that is faster-but-bigger vs slower-but-smaller) in what
the LLM4HLS / agentic-HLS research community (2023-2025) actually reports and optimizes.

Convention below: **SAID** = what the source states; **INFER** = my inference. Every system
cited with a URL.

---

## (a) Most relevant LLM4HLS systems / benchmarks — what each optimizes & reports

### HLSPilot — "first LLM-enabled HLS framework" (ICCAD 2024)
- arXiv: https://arxiv.org/abs/2408.06810 · ACM: https://dl.acm.org/doi/10.1145/3676536.3676781
- SAID: LLM generates/optimizes HLS code and pragmas; claims designs "comparable … and
  can even outperform manually crafted counterparts." **Crucially, it explicitly does NOT
  trust the LLM to pick pragma *parameters*** — quote: *"Since LLMs still face problems in
  determining the optimized pragma parameters precisely, we have a design space exploration
  (DSE) tool integrated for pragma parameter tuning."*
- INFER: performance-vs-manual is the headline framing (latency-oriented); the LLM picks
  *which* transformation, a deterministic DSE picks *how much*. This is the same division of
  labor HARPO makes with its recipe library.

### ChatHLS — fine-tuned multi-agent HLS repair + optimize (2025)
- arXiv: https://arxiv.org/abs/2507.00642 · HTML: https://arxiv.org/html/2507.00642v1
- SAID: Reports **repair pass rate 82.7%** over 612 test cases; **1.9×–14.8× speedup** on
  resource-constrained kernels vs baseline / GPT-4o / DSLs (Dahlia, Allo, HeteroCL);
  4.9× geomean speedup over SOTA DSLs. Metrics tracked: latency (cycles), DSP/FF/LUT.
- **Selection is CONSTRAINT-BASED, not a single scalar.** Pass Rate = fraction of cases
  where *latency ≤ threshold AND resources ≤ threshold*. When synthesis fails the metrics,
  an iterative refinement cycle (HLSTuner) re-tries.
- SAID (failure mode): acknowledges over-parallelization implicitly —
  *"incorrect allocation of optimization directives can lead to … resource over-utilization
  and synthesis errors."*
- SAID (pairing): validates **every** candidate through real synthesis on a target device
  (Xilinx ZCU106), not a predictor.

### HLStrans — dataset + method for LLM-driven C→HLS (2025) ★ most relevant to HARPO
- HTML: https://arxiv.org/html/2507.04315v2 (v1: …/2507.04315v1)
- SAID: 124k+ paired C/HLS programs. Four metrics: **Functional Accuracy** (testbench),
  **Synthesis Accuracy** (compiles to FPGA), **Speedup** (latency ratio orig→generated),
  and **%OPT = fraction achieving speedup >1× while passing correctness**. Speedup is the
  primary figure of merit, *within* (implicit) resource feasibility — designs exceeding device
  capacity are discarded.
- SAID (failure mode, explicit): *"LLM optimization may harm HLS code performance … some
  LLM-optimized kernels actually degrade performance (speedup <1×)"* — caused by LLM
  restructuring introducing loop dependencies, or *"pragmas inserted by LLMs may be less
  effective than default optimizations."* This is the closest published statement to
  HARPO's recipe-beats-raw-LLM result (315 vs 13194 LUT).
- SAID (pairing): LLM is paired with **MCTS + NSGA-II genetic DSE**, both driven by
  real-synthesis reward — i.e. the field does not let the LLM self-grade.

### HLS-Eval — benchmark + framework for LLMs on HLS (2025)
- arXiv: https://arxiv.org/abs/2504.12268
- SAID: A **correctness-first staged benchmark.** Four metrics mirror the HLS design cycle:
  **parseability → compilability → runnability (C-sim) → synthesizability**, plus
  **pass@k**. Quote: *"establishing clear baselines … for the broader LLM-for-hardware
  community."* No PPA/area-delay headline — it scores whether the LLM can produce a
  *valid* design at all, across k attempts.
- INFER: this is the de-facto "leaderboard" framing the community recognizes for *generation*
  competence. PPA quality is treated as a separate, downstream question.

### C2HLSC — LLM refactors C → synthesizable C (TODAES 2025)
- HTML: https://arxiv.org/html/2412.00214 · ACM: https://dl.acm.org/doi/full/10.1145/3734524
- SAID: Pure **functional-correctness** evaluation — iterative refinement on synthesis-tool
  error feedback; correctness checked via Known Answer Tests (KATs) and C-vs-Verilog
  equivalence (Modelsim). *Explicitly does not focus on resource utilization.*
- INFER: establishes the floor — "is it even synthesizable & correct" — before any PPA talk.

### Agentic-HLS — agentic reasoning for HLS QoR prediction (AI-for-EDA workshop 2024)
- arXiv: https://arxiv.org/abs/2412.01604 · HTML: …/html/2412.01604v1
- SAID: Predicts **validity, latency, and BRAM/LUT/FF/DSP**. Multi-metric, **no single
  figure of merit and no Pareto aggregation** — independent predictions; primary focus was a
  validity classifier. No discussion of over-parallelization.
- INFER: confirms the field reports PPA as a *vector*, not a scalar.

### "Can Reasoning Models Reason about Hardware? An Agentic HLS Perspective" (2025)
- arXiv: https://arxiv.org/abs/2503.12721 · review: https://www.themoonlight.io/en/review/can-reasoning-models-reason-about-hardware-an-agentic-hls-perspective
- SAID: Objective stated as **"minimize latency while adhering to area constraints"**;
  per-function **greedy selection of the lowest-latency option**. Comparative across models
  ("no single model consistently outperformed"). Notes models "inadequately modeled the
  dependencies and parallelism necessary."
- INFER: textbook **constrained-optimization** framing (minimize-latency-s.t.-area), the
  single most common selection rule in the field.

### Agent Factories for HLS — general-purpose coding agents on HW opt (2026 preprint)
- arXiv: https://arxiv.org/abs/2603.25719
- SAID (partial, PDF parse limited): multi-dimensional eval (correctness, latency/throughput,
  resource use); speed-vs-area trade-off rather than single-metric optima.

### ForgeHLS — large-scale HLS dataset (2025)
- HTML: https://arxiv.org/html/2507.03255v2 · PDF: …/pdf/2507.03255
- SAID: 429k designs. Per-design QoR = **worst-case latency + BRAM/FF/LUT/DSP**. Defines a
  composite resource scalar **ARU = mean(used/available) across the 4 resource types**, and
  ranks via **Pareto front in (latency, ARU)**: *"Pareto designs … the dominant solutions in
  the trade-off between latency and ARU, where no design can improve one … without sacrificing
  the other."* Pareto set further bucketed high/med/low resource.
- INFER: the cleanest published recipe for collapsing 4 resource numbers into ONE area axis
  (ARU) for a 2-D latency-vs-area Pareto — directly reusable by HARPO.

### iDSE — LLM-navigated HLS DSE (2025)
- PDF: https://arxiv.org/pdf/2505.22086 · HTML: …/html/2505.22086
- SAID: Objective = **Pareto-optimality in (latency, resource)**, quality measured by **ADRS**
  (Average Distance to Reference Set). Explicitly prunes **"aggressive parallelism directives …
  within large design footprints"** to avoid synthesis blowups — direct acknowledgment of the
  over-parallelization failure.

### Supporting DSE / metric references (non-LLM, define community vocabulary)
- "Parallel Programming for FPGAs" (Kastner et al.): https://arxiv.org/pdf/1805.03648 —
  canonical statement of the failure mode: *"greater unrolling yields unpredictably better and
  worse designs"*; unrolling is a **non-monotonic area–performance trade-off** (more unroll ≠
  better; BRAM port limits bottleneck the added PEs; some factors even produce wrong results).
- "Learning from the Past" DSE survey: https://dl.acm.org/doi/fullHtml/10.1145/3495531 and
  GNN-for-HLS-DSE: https://dl.acm.org/doi/10.1145/3570925 — establish **ADRS** as the standard
  DSE-quality metric and **Pareto front (latency vs area/power)** as the standard objective.
- MPM-LLM4DSE / GNN+LLM DSE: https://arxiv.org/html/2504.19649v3 — LLM-assisted DSE reports
  latency & resource prediction error reductions; multi-objective Pareto framing.

---

## (b) How the community MEASURES "better HLS" — the consensus

There is a clear, layered consensus across the works above:

1. **Correctness is a hard gate, evaluated FIRST and separately.** Every system stages it:
   parse → compile → C-sim (csim) → synthesize → (often) cosim / equivalence. HLS-Eval,
   C2HLSC, HLStrans, ChatHLS all gate on this before any PPA discussion. The community
   reports correctness as **pass@k** (HLS-Eval) or **pass rate / functional+synthesis
   accuracy** (ChatHLS, HLStrans). A design that fails correctness is not "worse" — it is
   *out*.

2. **Among correct designs, NOBODY uses a single universal scalar.** Two dominant idioms:
   - **Constrained optimization** (most common for *optimizer/agent* papers): *minimize
     latency subject to a resource/area budget*, with the budget set by the target device or
     the problem. ChatHLS (latency ≤ T ∧ resources ≤ T), the reasoning-models paper
     ("minimize latency while adhering to area constraints"), HLStrans (speedup, infeasible
     designs discarded).
   - **Pareto front in (latency, area)** (most common for *DSE/dataset* papers): ForgeHLS
     (latency vs ARU), iDSE, the classic GNN-DSE line. Quality of an *exploration* is scored
     by **ADRS** against a reference Pareto front.
   - **Speedup** is the favored *single reported headline number*, but it is always reported
     **alongside** a resource table and only counts when correctness holds (HLStrans %OPT,
     ChatHLS 1.9–14.8×).

3. **PPA is reported as a vector / table, not pre-collapsed.** LUT/FF/DSP/BRAM + latency are
   shown per design; ARU (ForgeHLS) is the one clean published example of collapsing the four
   resource numbers into a single normalized area axis for plotting.

4. **Area-delay product (ADP) is standard EDA vocabulary but is NOT the field's headline
   LLM4HLS metric.** ADP / energy-delay show up in the general DSE figure-of-merit literature
   (delay-area-energy trade-offs), yet none of the *LLM4HLS* systems surveyed adopt ADP as
   their primary selection rule — they prefer constrained-latency or explicit Pareto. INFER:
   leading with raw ADP would read as slightly out-of-idiom to this specific community.

---

## (c) Is the over-parallelization failure + recipe/DSE pairing acknowledged? (HARPO positioning)

**Yes on both — and this is HARPO's wedge, but the framing matters.**

- **Over-parallelization / area explosion IS a recognized failure mode**, but it is stated
  diffusely, not as a headline contribution:
  - HLStrans: explicit — LLM optimization can *degrade* performance / be *less effective than
    defaults* (speedup <1×). https://arxiv.org/html/2507.04315v2
  - iDSE: explicit — prunes "aggressive parallelism directives within large design footprints"
    to prevent synthesis blowups. https://arxiv.org/pdf/2505.22086
  - ChatHLS: explicit — directives causing "resource over-utilization and synthesis errors."
  - Kastner FPGA textbook: the *root cause* — unrolling is non-monotonic; more parallelism
    routinely costs area without buying latency. https://arxiv.org/pdf/1805.03648
  - INFER: No surveyed LLM4HLS paper *quantifies* a clean head-to-head of "raw LLM pragmas vs
    a deterministic recipe library" on the *same* kernel with an order-of-magnitude area gap.
    HARPO's 315 vs 13194 LUT (~42× area) is exactly that missing datapoint. That is a
    publishable, in-demand result for FPT'26 Track A.

- **Pairing the LLM with a deterministic/rule-based or DSE backend is the DOMINANT, blessed
  pattern — not a novelty by itself.** HLSPilot (LLM + DSE for parameters), HLStrans (LLM +
  MCTS + NSGA-II), iDSE (LLM-navigated Pareto DSE), ChatHLS (LLM + ground-truth synthesis loop).
  - INFER: HARPO should NOT claim "pairing an LLM with a non-LLM optimizer" as the
    contribution — the field already does this. The novel, defensible claims are:
    (1) a **curated recipe library of precise, area-safe pragma sets** that *beats raw-LLM
    pragmas on area by ~42×* on the same correct design (concrete, measured), and
    (2) **budget-awareness** as a first-class selection axis (cost-of-compute / synthesis
    budget while still landing a good PPA point) — under-explored vs the
    unlimited-synthesis-call DSE papers.

---

## (d) RECOMMENDATION — how HARPO should frame & choose its objective

**Headline recommendation: SATISFICE-THEN-AREA (constrained-latency selection), with a Pareto
view as the secondary presentation.** This is the most credible objective for this community.

Concretely, HARPO's selection rule, in priority order:

1. **Correctness is a hard gate (pass/fail), reported as pass@k or pass rate.** Mirror
   HLS-Eval / HLStrans / C2HLSC. An incorrect design is disqualified, never "ranked lower."
   This is non-negotiable to be taken seriously by reviewers.

2. **Among correct candidates, satisfice the binding constraint, then optimize the other axis.**
   Default rule: **meet the latency/II target (or resource budget) as a constraint, then pick
   the candidate that minimizes the *other* resource (area).** This is exactly ChatHLS's
   `latency ≤ T ∧ resources ≤ T` and the reasoning-models paper's "minimize latency s.t.
   area." It directly answers the faster-bigger vs slower-smaller question:
   - If a latency/II target is given → among designs that MEET it, choose **smallest area**
     (this is where the recipe library shines and the 315-LUT result lands).
   - If an area/device budget is given → among designs that FIT, choose **lowest latency**.

3. **Present the full candidate set as a (latency, area) Pareto front, and report ADRS if you
   have a reference set.** Borrow **ForgeHLS's ARU** (mean used/available over LUT/FF/DSP/BRAM)
   as your single normalized area axis so the front is 2-D and legible. Report per-design
   LUT/FF/DSP/BRAM + latency tables alongside (the field never pre-collapses PPA). ADRS shows
   exploration quality and is the recognized DSE-quality metric.

**Explicitly do NOT lead with area-delay-product as the selection scalar.** ADP is fine as a
*tie-breaker* or a single-number summary in a table, but no LLM4HLS system uses it as the
headline objective; leading with it reads as out-of-idiom and hides the correctness gate and
the constraint structure reviewers expect. **Speed-first** is also wrong as a default — the
whole point of HARPO's recipe library is area discipline, so a speed-first objective would
bury the contribution. **Defer** is unnecessary — the field has a clear convention to adopt.

**One-line recommendation:** Use **satisfice-then-area** (constraint-first: gate on
correctness, meet the latency/II-or-area budget, then minimize the remaining axis — area by
default), and *additionally* present a (latency, ARU) Pareto front + ADRS — this is the
selection idiom (ChatHLS / reasoning-models-HLS for the rule, ForgeHLS / iDSE for the view)
that this community already speaks, and it foregrounds HARPO's area-safe recipe win
instead of hiding it.

---

### Key URLs (quick index)
- HLSPilot: https://arxiv.org/abs/2408.06810
- ChatHLS: https://arxiv.org/abs/2507.00642
- HLStrans: https://arxiv.org/html/2507.04315v2
- HLS-Eval: https://arxiv.org/abs/2504.12268
- C2HLSC: https://arxiv.org/html/2412.00214
- Agentic-HLS: https://arxiv.org/abs/2412.01604
- Reasoning-about-HW (agentic HLS): https://arxiv.org/abs/2503.12721
- Agent Factories for HLS: https://arxiv.org/abs/2603.25719
- ForgeHLS: https://arxiv.org/html/2507.03255v2
- iDSE: https://arxiv.org/pdf/2505.22086
- MPM/GNN+LLM DSE: https://arxiv.org/html/2504.19649v3
- ACM "HLS Directives Design Optimization via LLM": https://dl.acm.org/doi/10.1145/3747291
- Kastner, Parallel Programming for FPGAs (failure mode): https://arxiv.org/pdf/1805.03648
- GNN for HLS DSE (ADRS/Pareto): https://dl.acm.org/doi/10.1145/3570925
- "Learning from the Past" DSE: https://dl.acm.org/doi/fullHtml/10.1145/3495531
