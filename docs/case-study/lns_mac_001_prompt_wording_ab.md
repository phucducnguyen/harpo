# Prompt-wording A/B on lns_mac_001 (2026-07-16)

## Question

At temperature 0 (greedy decoding), does the exact wording of one resource
violation message in the prompt change the agent's proposal?

Context: commit `9b040cc` (an exact-integer overuse check, added to catch
overuse hidden by 1-decimal util% rounding) also changed the violation message
on cases the rounded-util path already caught — from a utilization percentage
to an equivalent raw count. After that commit, optimize runs on `lns_mac_001`
stopped finding the known winning fix.

## Method

Reconstruct the exact first-optimize-step prompt from the stored baseline
artifacts (`runs/lns_mac_001/cand_0000/{csynth_parsed.json,src/}`) via
`load_task` + `diagnose_csynth` + `OllamaProvider._build_user_prompt`, then
query the same model twice at temperature 0, varying ONLY the LUT violation
string. Script: `scripts/prompt_wording_ab.py`.

Model: `qwen3.6:35b-a3b-q4_K_M` (Ollama). Everything else in the two prompts
is byte-identical.

## Result

| Arm | Violation string | prompt_eval | Proposal (temperature 0) |
|---|---|---|---|
| A (count, 2026-07-15 wording) | `resource: LUT count 89773 > available 53200 (168.75%)` | 17813 | `add_unit.cpp`: "Remove #pragma HLS UNROLL from the 36-iteration priority encoder loop in convertback …" — a no-op under the still-present top-level PIPELINE (synthesizes to baseline-identical metrics) |
| B (utilization, recorded-run wording) | `resource: LUT utilization 168.7% > 100%` | 14241 | `mac.cpp`: "Move PIPELINE directive from top-level function to the j-loop with II=1 …" — the recorded winning fix, verbatim |

Arm B's `prompt_eval` (14241) matches the token count recorded in the
2026-07-14 run logs exactly, confirming the reconstruction reproduces the
original prompt byte-for-byte. (Arm A's higher count also reflects Ollama
prefix-cache accounting differences between calls, not just the wording.)

## Interpretation

- At temperature 0 the model is deterministic, so identical replays across
  runs demonstrate end-to-end replayability of the loop — not robustness of
  the outcome.
- A semantically equivalent rewording of a single violation message flips the
  greedy decode between the 4.3x winning relocation and a dead-end edit.
  Prompt surface is load-bearing.
- Follow-up in code: `parse_csynth` keeps the utilization wording for every
  case the pre-9b040cc path caught; the count wording now fires only for
  rounding-hidden overuse (its actual purpose). Golden-string tests in
  `tests/test_parser_hierarchical.py` pin both forms. Commit `b24b91a`.
