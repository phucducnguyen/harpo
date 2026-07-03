# HLS Objective Functions for Candidate Selection — Research Notes for HARPO

**Question this answers:** When HARPO has two *correct* designs and one is faster but much
larger, how should an autonomous (no-human-in-the-loop) agent rank them?

**Concrete trigger case:** design A = II/interval 256, 315 LUT vs design B = II 128 but
13,194 LUT — roughly **42× the area for 2× the throughput**. A naive "lower interval wins"
(speed-first) objective picks B; almost no resource-constrained methodology would.

Sourcing note: "[ESTABLISHED]" = stated in a cited source. "[INFERENCE]" = our reasoning for
HARPO, built on those sources.

---

## (a) The menu of objective formulations used in HLS DSE

Each entry: what it optimizes + a one-line trade-off, with a source.

1. **Pareto-optimal set (no single scalar).** DSE returns the set of non-dominated
   (latency, area[, power]) points; a design is kept iff no other design beats it on every
   axis. *Trade-off:* most honest representation of the design space, but **returns multiple
   points and defers the final pick to a human / a downstream selector** — it does not by
   itself answer "which one."
   Source: Graph Neural Networks for HLS DSE, ACM TODAES — DSE framed as a multi-objective
   problem whose goal is to find the Pareto-optimal set minimizing latency and resource use.
   https://dl.acm.org/doi/full/10.1145/3570925

2. **Constraint-then-optimize (satisfice the target, then minimize the other axis).** Treat
   one axis as a hard constraint (meet a timing/II/throughput target, or stay within an FPGA
   resource budget) and optimize the other axis only within the feasible region. This is the
   classic ASIC/FPGA framing. *Trade-off:* deterministic and autonomous-friendly (yields a
   single answer once the constraint is fixed), but **requires you to set the constraint /
   target up front** — a bad target hides good designs.
   - Performance-primary form (minimize latency subject to resource budget):
     "Prometheus" / Holistic Optimization Framework for FPGA Accelerators formulates DSE as a
     non-linear program **minimizing overall latency under strict resource constraints**
     (DSP/BRAM budgets), treating latency as the objective and resources as constraints rather
     than co-equal objectives. https://arxiv.org/html/2501.09242v5
   - Resource-as-constraint form is the basis of AutoDSE / Merlin-based DSE, which prunes the
     space by **FPGA footprint (DSP/FF/LUT) and synthesis-time budgets** and searches for the
     best-performing point that fits.
     AutoDSE (ACM TODAES 2022): https://dl.acm.org/doi/10.1145/3494534 ·
     arXiv preprint: https://arxiv.org/abs/2009.14381
   - Area-minimization form (meet timing first, then shrink area) is described as standard
     FPGA practice — "ensure timing closure, then optimize for area / device utilization."
     Vendor-agnostic HLS optimization playbook: turn C/C++ into RTL that "meets your
     throughput, latency, area, and power targets," then minimize the resources required.
     https://dev.to/ai_pics_6442ad429fc2ff12f/how-to-optimize-hls-designs-for-fpgas-a-practical-vendor-agnostic-playbook-49k0

3. **Weighted sum of normalized PPA.** Scalarize: `cost = w_lat·L̂ + w_area·Â + w_pwr·P̂`
   over normalized metrics. *Trade-off:* gives a single number an agent can sort on, but the
   **weights are arbitrary and hard to justify**, and a pure weighted sum cannot reach points
   on non-convex regions of the Pareto front. Used by ML/learning DSE tools that fold
   DSP/FF/LUT/power/latency into one synthesizability-aware multi-objective score.
   AutoHLS (multi-objective over DSP, FF, LUT, power, latency): https://arxiv.org/pdf/2403.10686

4. **Product / figure-of-merit metrics — Area-Delay Product (ADP), Energy-Delay Product
   (EDP).** A single scalar = area × delay (or energy × delay). *Trade-off:* one number that
   captures the area↔speed balance, **but it is scale-free and rewards trading huge area for
   small speed gains and vice-versa with no cap** — it has no notion of "good enough."
   ADP = product of die area and delay; "the balanced parameter for overall performance
   comparison of various architectures rather than the area and delay individually"; a smaller
   ADP signifies a better balance between area and delay.
   https://arxiv.org/pdf/2107.02762 (ADP-efficient FPGA design) ·
   Power/Energy-Delay product background: https://www.bohrium.com/en/sciencepedia/feynman/keyword/power_delay_product

5. **Bottleneck-guided / lexicographic-tiered search.** Iteratively attack the current
   limiting factor (AutoDSE) or impose a strict priority ordering of objectives so a
   single-objective optimizer can be reused without computing a Pareto front (quantized
   lexicographic weighted sum). *Trade-off:* mimics expert manual tuning and converges fast,
   but the **priority order is a design decision baked in by the author**.
   AutoDSE bottleneck-guided coordinate optimizer: https://github.com/UCLA-VAST/AutoDSE ·
   Lexicographic / strict-priority objective ordering (general):
   https://www.researchgate.net/publication/292047802_A_Theory_of_Lexicographic_Optimization_for_Computer_Networks

---

## (b) Which formulations are standard for "two correct designs, one faster, one smaller"?

[ESTABLISHED] The literature does **not** treat "faster is always better." The two dominant
production framings both make the area↔speed trade-off explicit:

- **Constraint-then-optimize** is the mainstream FPGA/HLS framing: set a throughput/II/timing
  *target*, then minimize resources — or set a *resource budget*, then maximize performance
  within it (AutoDSE/Merlin, Prometheus, and vendor HLS guidance).
  https://arxiv.org/html/2501.09242v5 · https://dl.acm.org/doi/10.1145/3494534 ·
  https://dev.to/ai_pics_6442ad429fc2ff12f/how-to-optimize-hls-designs-for-fpgas-a-practical-vendor-agnostic-playbook-49k0
- **Pareto** is the standard *academic DSE* output, but it deliberately returns a *set*, so it
  does not by itself pick between A and B without an additional rule.
  https://dl.acm.org/doi/full/10.1145/3570925

[INFERENCE] In our concrete case, every resource-aware methodology rejects B: 42× area for 2×
throughput is the textbook "diminishing returns" region. Only an unbounded speed-first or a
naive ADP objective would even consider B (and ADP here actually *favors A*: ADP_A ∝ 315·256 ≈
80.6k vs ADP_B ∝ 13194·128 ≈ 1.69M — A's ADP is ~21× better, so B is not even ADP-competitive).

---

## (c) Pros/cons for an AUTONOMOUS agent (no human in the loop)

### Satisfice-then-minimize-area (meet an II/throughput target, then minimize LUT/area)
- **Pros:** deterministic and fully automatable; yields exactly one winner; matches mainstream
  FPGA practice; naturally caps resource blow-up because area is the thing being minimized once
  the target is met; explainable ("met II target X, smallest area that did").
  https://arxiv.org/html/2501.09242v5
- **Cons:** needs a target II/throughput to be supplied or inferred; if the target is set too
  loose it may leave performance on the table, too tight it may be infeasible. [INFERENCE]

### Speed-first / lexicographic (minimize latency/II first, area only as a tie-break)
- **Pros:** trivial to implement; matches "performance is the point of HLS acceleration"
  intuition; what the LLM did by default.
- **Cons:** [ESTABLISHED via the unrolling literature] with **no area bound it drives full
  unrolling and resource explosion for marginal latency gains** — exactly HARPO's observed
  failure. Loop unrolling is an area–performance trade-off where larger factors consume more
  resources for lower latency, with **diminishing returns** (memory-port bottlenecks) and cases
  where over-unrolling *hurts both* latency and area.
  https://arxiv.org/pdf/1805.03648 (Parallel Programming for FPGAs — port/BRAM bottlenecks) ·
  https://ieeexplore.ieee.org/document/8326978 (Exploration of loop unroll factors). An
  autonomous agent on this objective will reliably pick the 13,194-LUT design.

### Area-Delay Product (single scalar = area × delay)
- **Pros:** one number, no target to set, directly sortable by an agent; rewards balanced
  designs; in this case it *correctly* prefers A.
  https://arxiv.org/pdf/2107.02762
- **Cons:** scale-free with **no "good enough" notion** — it will happily approve a 10× area
  increase for an 11× speedup (ADP improves) even if the agent has no room/need for that area,
  and conversely reject a small-but-fast design if a bloated one edges out the product. It also
  silently mixes axes the user may want kept separate (a hard LUT ceiling). [INFERENCE: pros/cons
  applied to the agent case; ADP definition is established.]

---

## (d) Recommendation for HARPO

**Recommended objective: satisfice-then-minimize-area (constraint-then-optimize), with ADP as a
secondary tie-break, never speed-first.**

Concretely, the candidate-selection function should be **lexicographic over three tiers**:

1. **Correctness** — must pass (HARPO already enforces this; it is the hard gate).
2. **Throughput/II constraint** — meet the target II (or accept the best II if no target is
   given **and** the area cost per II-improvement is below a guard ratio). The guard ratio
   directly kills the 42×-area-for-2×-throughput trap.
3. **Minimize area (LUT/FF/DSP/BRAM)** within tier-2 feasibility; break ties with **lower ADP**.

**Reasoning:**
- It is the mainstream, defensible FPGA/HLS framing (Prometheus, AutoDSE/Merlin, vendor
  guidance) — not an invented metric. https://arxiv.org/html/2501.09242v5 ·
  https://dl.acm.org/doi/10.1145/3494534
- It is **autonomous-safe**: deterministic, single winner, explainable in one sentence, and
  structurally immune to the resource-explosion failure mode the LLM exhibited, because area is
  the minimized quantity once throughput is satisfied. The unrolling literature shows speed-first
  *will* over-unroll without this bound. https://arxiv.org/pdf/1805.03648
- On the concrete case it selects **A** (315 LUT, II 256): A already has the far better ADP
  (~21×), and B's 42×-area-for-2× is squarely in diminishing-returns territory. The only
  objectives that would pick B (unbounded speed-first) are exactly the ones the literature warns
  against.
- ADP alone is rejected as the *primary* objective because it lacks a "good enough" stop and can
  be gamed in both directions; it is a fine *tie-breaker* among designs that already meet the
  constraint. https://arxiv.org/pdf/2107.02762

**Defer** only the *value* of the II target and the area-per-II guard ratio to HARPO config /
the user when supplied — but the agent must always have a sane default (e.g. reject any
Pareto-move whose %area-increase exceeds K× its %throughput-gain) so it never needs a human to
avoid the explosion case.

---

## Source list
- Graph Neural Networks for HLS DSE (Pareto framing): https://dl.acm.org/doi/full/10.1145/3570925
- AutoDSE (ACM TODAES 2022): https://dl.acm.org/doi/10.1145/3494534 · preprint https://arxiv.org/abs/2009.14381 · code https://github.com/UCLA-VAST/AutoDSE
- Prometheus / Holistic Optimization Framework — minimize latency under resource constraints: https://arxiv.org/html/2501.09242v5
- Vendor-agnostic HLS optimization playbook (meet targets, then minimize resources): https://dev.to/ai_pics_6442ad429fc2ff12f/how-to-optimize-hls-designs-for-fpgas-a-practical-vendor-agnostic-playbook-49k0
- AutoHLS (multi-objective DSP/FF/LUT/power/latency): https://arxiv.org/pdf/2403.10686
- Area-Delay Product definition/use: https://arxiv.org/pdf/2107.02762 · Power/Energy-Delay product background: https://www.bohrium.com/en/sciencepedia/feynman/keyword/power_delay_product
- Loop unrolling area↔latency trade-off, diminishing returns, over-unroll hurting both: https://arxiv.org/pdf/1805.03648 · https://ieeexplore.ieee.org/document/8326978
- Lexicographic / strict-priority objective ordering: https://www.researchgate.net/publication/292047802_A_Theory_of_Lexicographic_Optimization_for_Computer_Networks
