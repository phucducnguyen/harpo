# How FPGA / HLS design competitions actually score entries

Research for HARPO (FPT'26 AMD FPGA Design Competition, Track A "LLM4HLS").
Goal: pick the agent's candidate-selection objective (how it ranks Performance / Power / Area
designs internally) so it matches what the real rubric rewards.

Date of research: 2026-06-15. Every claim below is tagged **FOUND** (quoted/paraphrased from a
cited source) or **INFERRED** (my reasoning on top of the sources).

---

## (a) FPT'26 Track A (LLM4HLS) — what is actually published

**The competition page exists and Track A is real.** Source:
<https://fpt2026.uark.edu/fpt26-design-competition/> (FPT'26, University of Arkansas).

What it says (FOUND — verbatim quotes pulled from that page):

- Track A goal: develop an autonomous AI agent that **generates, debugs, and optimizes HLS code
  iteratively**, under **strict tool-invocation budgets**, aiming for functional correctness and
  good PPA.
- **Evaluation dimensions (verbatim):** *"Submitted entries will be evaluated based on the
  following primary dimensions: **correctness**, **PPA metrics**, and **problem difficulties**."*
- **Correctness gate (verbatim):** *"Prioritization of correctness issue resolution before PPA
  optimization."*  ← This is the single most load-bearing sentence for our objective design.
- **Tool budget (verbatim):** *"Maximum iterations allowed calls to csim, cosim, and synth, or an
  equivalent unified credit budget."* (Per-task; **exact numeric limits are NOT published yet.**)
- **Target platform / tools:** AMD-supported FPGA platforms; AMD or open-source tools permitted;
  tool version + clock target specified per task in the target constraints.
- **Final-stage scoring (verbatim):** *"The final evaluation will be based on two aspects:
  **performance (80%) and innovation (20%)**."*  Note: this is the *finalist / in-person* ranking,
  applied to the shortlist — not the preliminary automated scoring of a submission.
- **Deadlines:** Registration **2026-06-30**, Submission **2026-08-01**, Shortlist **2026-08-15**.

**What is NOT published (the real rubric gap — FOUND as an absence):** the page gives the
*dimensions* (correctness, PPA, difficulty) but **no concrete preliminary scoring formula** — no
weights between correctness and PPA, no statement of weighted-sum vs. Pareto vs.
constraint-then-minimize, no definition of whether "Performance" means latency or throughput, and no
numeric tool-call budgets. The "80% performance / 20% innovation" weighting applies only to the
final human-judged stage.

**Bottom line for (a):** The two facts the organizers *have* committed to are (1) **correctness is
gated/prioritized before PPA**, and (2) **PPA is the quality axis**, with **performance dominant
(80%) at the final stage**. The precise preliminary figure-of-merit is **not yet published.**

---

## (b) Concrete scoring rules from prior / closely related contests

### 1. FPL'26 — Agentic FPGA Backend Optimization Competition (AMD/Xilinx) — *most directly analogous*
Source: <https://xilinx.github.io/fpl26_optimization_contest/> and the scoring page
<https://xilinx.github.io/fpl26_optimization_contest/score.html>

This is the closest living analogue: an **agent**, under a **cost/runtime budget**, optimizing an
FPGA design. FOUND — exact figure of merit (verbatim from the score page):

> **Benchmark Score = α − (0.1 × α)β − (0.1 × α)γ**
> where **α = ΔFmax improvement (MHz)**, **β = OpenRouter cost (USD)**,
> **γ = (1/3600) × wall-clock runtime (seconds)**.

- **Hard constraint first:** designs must maintain *"logical equivalence and staying fully placed
  and routed"* — i.e. **correctness/legality is a gate**; you only score if the design is valid.
- **Primary quality metric:** Fmax improvement (a *performance* axis). Organizers state *"the
  biggest component of the contest score will be Fmax improvement."*
- **Budget is in the score, not just a cutoff:** API cost (β) and runtime (γ) are *subtracted*,
  each scaled to 10% of the achieved Fmax gain. So spending more tool budget is penalized
  proportionally to how much performance you bought with it.
- **Area and power are NOT scored** here.
- **Ranking:** mean rank across benchmarks, lower is better.

### 2. FPT'26 final-stage (same family, prior bullet) — performance 80% / innovation 20%
Source: <https://fpt2026.uark.edu/fpt26-design-competition/> (already cited above).
FOUND: confirms **performance dominance** at the human-judged stage.

### 3. FPT'25 Design Competition — final-stage weighting
Source: <https://fpt2025.shanghaitech.edu.cn/design-competition/> (full rules PDF:
<https://fpt2025.shanghaitech.edu.cn/fpt25-design-contest.pdf>)
FOUND (verbatim final-stage split): *"Performance & technical innovation (40%)"*,
*"On-site defense & demo (40%)"*, *"Technical Paper (20%)"*. Per-track numeric metrics live in the
PDF appendices (evaluation metrics + scoring criteria per track). INFERRED: performance is again
the dominant *technical* axis; the FPT family leans on a performance-weighted holistic score.

### 4. DAC System Design Contest (DAC-SDC) — fully specified quantitative formula
Sources: <https://byuccl.github.io/dac_sdc_2022/evaluation/>,
2019: <http://www.cse.cuhk.edu.hk/~byu/2019-DAC-SDC/>,
challenge paper: <https://ar5iv.labs.arxiv.org/html/1809.00110>,
analysis: <http://scis.scichina.com/en/2024/182401.pdf>

This contest combines accuracy, throughput, and energy — and is a textbook **constraint-then-score**
design. FOUND:
- **Throughput is a hard floor with a penalty:** there is a minimum FPS (10 FPS FPGA / 20 FPS GPU);
  if you miss it, accuracy is *scaled down*:
  `IoU(real) = IoU(measure) × min(FPS, requirement)/requirement`.
- **Accuracy floor:** minimum IoU 0.7 or a penalty applies.
- **Energy term:** `ES_i = max{0, 1 + 0.2·log_x(Ē/E_i)}` (x=2 FPGA, x=10 GPU).
- 2022 combined score (verbatim form): `Score = 10² / log2(Energy) × Max(ReLU([1 − 5·ReLU(0.7 −
  IoU)]), 0.1) × ReLU([1 − ReLU(1 − FPS/30)])`.
- **Pattern:** **meet the performance/quality constraints first, then optimize the efficiency
  (energy) term.** Missing a constraint doesn't disqualify — it multiplies your score toward zero.

### 5. FCCM 2026 Competition — holistic, qualitative
Source: <https://www.fccm.org/fccm-2026-competition/>
FOUND (verbatim weights): **Technical Merit 40% / Innovation 30% / Practical Impact 20% / Clarity
10%.** No quantitative PPA formula — this is a demo-judged contest, less relevant as a QoR objective
model, but confirms that the broader FPGA-contest culture also weights "technical merit + innovation"
heavily.

### 6. HLS-agent academic literature (how the field defines the QoR objective)
These aren't competitions but they *are* the prior art HARPO competes against, and they show the
de-facto objective the field has converged on.

- **Agentic-HLS** (AI-for-EDA Workshop 2024) — <https://arxiv.org/html/2412.01604>
  FOUND: predicts/optimizes **validity (classification) + latency in cycle counts + utilization of
  BRAM/LUT/FF/DSP**. Validity (correctness) is treated as the first-order gate ("significantly
  affected RMSE"); latency + resource utilization are the quality axes.
- **"Agent Factories for High-Level Synthesis"** — <https://arxiv.org/html/2603.25719>
  FOUND — explicit objective (Eq. 2, verbatim): `min L_total(x) s.t. Σ A_km·x_km ≤ A_budget`, and
  final selection `D* = argmin_d L(d) s.t. A(d) ≤ A_budget`. Plainly:
  **minimize latency subject to a hard area budget**; timing closure + area feasibility are
  *constraints*, latency is the *objective*. QoR is reported as **speedup over baseline**.
- **ChatHLS** — <https://arxiv.org/pdf/2507.00642> FOUND: reward model uses synthesis success +
  warnings + resource usage + latency + throughput; "QoR-aware reasoning." (Multi-signal, but
  synthesis success / correctness is the precondition.)
- ML Contest for Chip Design with HLS (2024): predicting validity + latency (cycles) + BRAM/LUT/FF/
  DSP utilization — same metric set as Agentic-HLS.

---

## (c) The common pattern across all of these

INFERRED synthesis, grounded in the sources above:

1. **Correctness / legality is always a GATE, never a weighted term.** FPT'26 ("correctness before
   PPA"), FPL'26 ("logical equivalence … fully placed and routed"), DAC-SDC (accuracy/FPS floors),
   Agentic-HLS (validity classifier first). You do not trade correctness for PPA — an incorrect
   design scores ~0 regardless of how fast/small it is.

2. **Performance is the dominant quality axis once correct.** FPT'26 final = 80% performance;
   FPL'26 = "biggest component is Fmax"; the academic objective is "minimize latency". Area/power
   are secondary.

3. **Area/power usually act as a CONSTRAINT or tie-breaker, not the primary objective.** The
   strongest HLS-agent prior art (Agent Factories) makes this explicit: *area is a hard budget,
   latency is minimized within it.* DAC-SDC folds energy in as a softer multiplicative term *after*
   the accuracy/throughput floors. None of the HLS-focused contests make smallest-area the top
   objective.

4. **Tool/compute budget is real and increasingly *scored*, not just capped.** FPT'26 imposes
   csim/cosim/synth call budgets; FPL'26 actually *subtracts* cost and runtime from the score
   (~10% of the performance gain each). So a budget-aware agent should treat each synth/cosim call
   as having a price, and prefer reaching a target with fewer, cheaper calls.

5. **"Problem difficulty" weighting (FPT'26 specific):** harder problems are worth more — INFERRED
   implication: the agent should not over-spend budget polishing easy wins; allocate budget toward
   solving/correcting hard problems, where the marginal score is highest.

**The recurring shape is lexicographic-with-a-constraint:** `correct?` → if yes, `meet the
performance/throughput target` → then `minimize resources within the area budget`, all while
spending as little tool budget as possible.

---

## (d) RECOMMENDATION for HARPO's candidate-selection objective

**Choose: "satisfice throughput/latency to a target, then minimize area"** — i.e. a lexicographic
*constraint-then-minimize* objective, with correctness as the absolute precondition and tool-budget
as a cost penalty layered on top.

Concretely, rank candidate designs by this priority order:

1. **Correctness gate (hard):** must pass csim and (where budget allows) cosim. A non-correct
   candidate is never selected over a correct one, ever. (Matches FPT'26 "correctness before PPA",
   FPL'26 legality gate, Agentic-HLS validity-first.)
2. **Performance target (satisfice):** meet the per-task clock target and the latency/II goal. Once
   a candidate meets the target, *additional* performance is a weak tie-breaker, not a reason to
   keep burning budget. (Matches DAC-SDC's "meet the FPS floor" structure and the per-task
   `target constraints` FPT'26 describes.)
3. **Area / resources (minimize):** among target-meeting correct candidates, prefer the smallest
   resource footprint within the FPGA's `Abudget`. (Directly matches Agent Factories'
   `min L s.t. A ≤ A_budget`, generalized to "meet timing then shrink".)
4. **Tool-budget cost (penalty / efficiency):** prefer the candidate (and the search path) that
   reached the above with fewer/cheaper csim/cosim/synth calls. (Matches FPT'26 budget config and
   FPL'26's explicit cost+runtime subtraction.)

### Why this over the alternatives

- **vs. "speed-first lexicographic" (latency first, area last):** Tempting, because FPT'26 final is
  80% performance and FPL'26 is Fmax-driven. But pure speed-first keeps spending budget chasing
  latency past the point of diminishing returns, which (a) wastes the *scored* tool budget and (b)
  ignores that FPT'26 lists Power and Area as real PPA dimensions. **Satisficing performance then
  minimizing area captures the 80% performance weight (you DO hit the target) while still scoring on
  the A and P of PPA — and it stops wasting budget once the target is met.** This is the safer
  superset of speed-first.

- **vs. "efficiency product" (area-delay product / latency × resources):** A single scalar ADP is
  clean, but it lets a candidate "buy back" a missed timing target with tiny area — exactly the
  correctness-/constraint-gate violation the contests punish. ADP also has no natural place for the
  correctness gate or the tool-budget penalty, and it doesn't match any of the HLS-contest rubrics
  found (none use a pure ADP). Keep ADP only as an *internal tie-breaker* among candidates that
  already meet timing, if you want a finer area/latency trade than step 3 alone.

- **vs. "defer until the FPT'26 rubric is published":** Not recommended. The preliminary numeric
  formula isn't out, **but the two committed facts (correctness-before-PPA; performance-dominant
  PPA) plus the strong consensus across FPL'26, DAC-SDC, and the HLS-agent literature already
  determine the objective's shape.** The satisfice-then-minimize objective is robust to whatever
  exact weights FPT'26 publishes: it wins under a weighted sum (you hit performance and reduce
  area+power), under Pareto ranking (you land on the Pareto front), and under a constraint-satisfaction
  rubric (you satisfy the constraint by construction). Deferring stalls the agent's core design for
  no information gain. **Re-check the FPT'26 page near submission for the exact preliminary formula
  and tune the performance *target value* and budget penalty weight then — but don't wait to build.**

### Implementation note (INFERRED, for the team)
Make the three knobs explicit and rubric-tunable, because the published rubric mainly affects their
*values*, not the *structure*:
- the **performance target** per task (from the task's `target constraints`),
- the **area budget** (the target FPGA's resources),
- the **budget-cost weight** (how hard to penalize an extra synth/cosim call).
Set the budget-cost weight using FPL'26's calibration as a sane prior (≈10% of the marginal
performance gain), then adjust once FPT'26's csim/cosim/synth limits are announced.

---

## Source list (all URLs)

- FPT'26 Design Competition (Track A / LLM4HLS): <https://fpt2026.uark.edu/fpt26-design-competition/>
- FPL'26 Agentic FPGA Backend Optimization Competition: <https://xilinx.github.io/fpl26_optimization_contest/>
- FPL'26 scoring criteria: <https://xilinx.github.io/fpl26_optimization_contest/score.html>
- FPT'25 Design Competition: <https://fpt2025.shanghaitech.edu.cn/design-competition/>
- FPT'25 rules PDF: <https://fpt2025.shanghaitech.edu.cn/fpt25-design-contest.pdf>
- DAC-SDC 2022 evaluation: <https://byuccl.github.io/dac_sdc_2022/evaluation/>
- DAC-SDC 2019: <http://www.cse.cuhk.edu.hk/~byu/2019-DAC-SDC/>
- DAC-SDC challenge paper (arXiv 1809.00110): <https://ar5iv.labs.arxiv.org/html/1809.00110>
- DAC-SDC low-power analysis: <http://scis.scichina.com/en/2024/182401.pdf>
- FCCM 2026 Competition: <https://www.fccm.org/fccm-2026-competition/>
- Agentic-HLS (arXiv 2412.01604): <https://arxiv.org/html/2412.01604>
- Agent Factories for HLS (arXiv 2603.25719): <https://arxiv.org/html/2603.25719>
- ChatHLS (arXiv 2507.00642): <https://arxiv.org/pdf/2507.00642>
- IEEE LAD 2026 (LLM-Aided Design conf., related venue): <https://www.sigarch.org/call-contributions/2nd-ieee-international-conference-on-llm-aided-design-lad-2026/>
