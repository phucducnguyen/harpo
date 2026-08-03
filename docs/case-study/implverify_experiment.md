# Multi-fidelity impl-verify experiment (2026-07-16)

Research question (paper-4 seed): when a budgeted agent loop explores on cheap
csynth estimates and post-route-measures the top-K finalists
(`optimize --impl-verify 3`), does ground truth pick a **different winner**
than the estimates?

**Answer: yes — on 1 of 4 tasks (atax_001) the measured winner differs from
the estimate winner, via a clean area-ranking reversal.** On the other three
tasks the winners agree, but the estimate error is large and inconsistent in
direction on every task: LUT estimates ran ~2.0–2.5x pessimistic (winner
pairs 2.03–2.46x) while post-route clock came in *worse* than the csynth
estimate on 11 of the 12 measured candidates (exception: lns_mac cand_0001,
est 9.897 → measured 9.107 ns) — on atax_001 the baseline that csynth scored
at 6.923 ns actually **fails 10 ns timing post-route** (10.003 ns).

## Setup

- Tasks: `lns_mac_001` + the 3 PolyBench-style optimize tasks
  (`atax_001`, `bicg_001`, `gemm_001`), part `xc7z020clg400-1` @ 10 ns,
  objective `satisfice_then_area`, repo-default budgets.
- Providers: `lns_mac_001` ran `--provider ollama`
  (`qwen3.6:35b-a3b-q4_K_M`); PolyBench tasks ran the default
  `recipe,ollama` order (all accepted proposals came from recipes).
- Feature under test: `--impl-verify 3` — post-route-measure (Vitis
  `export_design -flow impl`) the top-3 csynth-passing candidates + baseline;
  declare the winner from MEASURED PPA; estimates are recorded alongside.
- Full run records (scrubbed to repo-relative paths):
  `implverify_<task>_2026-07-16.json` in this directory.

## Winner table

| task | improved | estimate winner | measured winner | diverged |
|---|---|---|---|---|
| lns_mac_001 | yes | cand_0001 | cand_0001 | no |
| atax_001 | yes | cand_0002 | **cand_0003** | **YES** |
| bicg_001 | yes | cand_0002 | cand_0002 | no |
| gemm_001 | no (baseline stands) | cand_0000 | cand_0000 | no |

## The divergence (atax_001)

All three finalists satisfice the throughput target; the objective then
minimizes area. Estimated LUT ordering fully **reverses** post-route:

| candidate | csynth LUT (rank) | post-route LUT (rank) | post-route clock |
|---|---|---|---|
| cand_0002 | 3907 (1st) | 1923 (2nd) | 9.475 ns |
| cand_0001 | 3994 (2nd) | 1927 (3rd) | 9.590 ns |
| cand_0003 | 4068 (3rd) | **1814 (1st)** | 9.119 ns |

The candidate the estimates ranked *last* is the smallest **and** fastest
of the three finalists after place & route. Scoring estimates alone ships
cand_0002; measuring ships cand_0003.

Margin caveat (added 2026-08-02 after independent audit): the robust
component is the first-place flip — cand_0003 beats the estimate winner by
109 LUT (6.0%). The 2nd↔3rd swap is 4 LUT (0.2%), inside single-run P&R
noise (two runs of one design differed by 69 LUT / 0.255 ns — see the
silicon-leg vs impl-verify pair for lns_mac run-1 winner), so that pair
should be read as unordered, not "fully" reversed. Each candidate got
exactly one P&R run at the default seed; the same resolution bound applies
to atax baseline's 0.003 ns timing fail and bicg baseline's 0.002 ns pass —
the ~3 ns estimate error is real, the side of the line is within noise.
(The measured pool also contains atax cand_0000 at 1,502 LUT — smaller than
cand_0003 but not a finalist: 304 cycles vs the 280 target, timing fail.)

## Secondary finding: estimate error is bidirectional

- **Area: pessimistic everywhere.** lns_mac 21013→8527 (2.46x), atax
  3907→1923 (2.03x), bicg 3596→1578 (2.28x), gemm 1238→573 (2.16x).
  (Consistent with the 2.4x gap measured manually in `silicon/` on 7/15.)
- **Timing: optimistic almost everywhere.** csynth estimated 6.9–9.9 ns on
  these designs; 11 of the 12 measured candidates came in slower post-route
  (lns_mac cand_0001 alone came in faster, 9.897→9.107 ns). A second
  estimate-pass→measured-fail flip hides in gemm_001: cand_0001 (est
  6.912 ns) fails post-route at 10.168 ns (slack −0.168) — it never
  threatened the winner only because it was already rejected on estimated
  PPA, but an estimate-only loop would have recorded it as timing-clean.
  And atax_001's baseline
  flipped from estimate-passing (6.923 ns) to a post-route **timing failure**
  (10.003 ns). An estimate-only loop would report that baseline as meeting
  timing.

## Reading

One task in four is enough to make the point: the cheap-estimate ranking is
not reliably the real ranking, and only measurement can tell you whether it
was. The cost was one `export_design -flow impl` run per finalist
(top-3 + baseline) — the "expensive rung" stayed a small constant per task.

Notes for the paper: gemm_001's honest no-improvement (recipes' partition
proposals didn't beat baseline under satisfice_then_area) still exercised the
rung — the measured pool confirmed the baseline stands. lns_mac_001's
baseline is excluded from its pool by construction (fails csynth checks:
`timing_fail` at 10.104 ns vs the 10 ns target, plus resource overuse at
168.7% estimated LUT). The exclusion is
estimate-level only: the 2026-07-17 baseline P&R (`silicon/run_baseline_impl.tcl`)
showed that design does place — 25,853 LUT (48.6%), timing met — i.e. the
estimator itself misclassified it, which is this experiment's point.
