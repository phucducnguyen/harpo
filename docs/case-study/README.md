# Case-study run records — lns_mac_001 (LNS log8 MAC)

Committed, replayable evidence for the follow-up case-study paper (HARPO
applied to a real research artifact — the author's 2024 MS-project LNS MAC,
2026 fixed datapath). Same convention as `docs/ablations/`: each JSON is the
verbatim result of one agent run, copied from `runs/lns_mac_001/`.

Provenance that applies to every record here (recorded per-file too):

- **Task:** `tasks/lns_mac_001/` — snapshot of `lns-log8-mac` @ `9c977d3`
  (see the task README for flattening + design choices).
- **Toolchain:** Vitis HLS 2025.2, Linux; part `xc7z020clg400-1` @ 10 ns.
- **LLM:** local **`qwen3.6:35b-a3b-q4_K_M`** served by Ollama on a single
  consumer RTX 5090 (32 GB) — no commercial/frontier API, $0 LLM cost. Since
  the `model_id` provenance change, every `propose` event in these JSONs also
  records the model tag that produced the patch.
- **Baseline finding (2026-07-14):** the archived design's own top-level
  `#pragma HLS PIPELINE` yields LUT **168.7%** of xc7z020 capacity
  (89,773 / 53,200) and misses timing (10.104 ns vs 10 ns) — status
  `timing_fail` + `resource_overuse` violation. The over-parallelization
  failure mode the HARPO paper argues about, occurring in the wild.
- **Scope caveat:** the 2024 report's tables target larger parts
  (Artix/Kintex/Virtex sweep); numbers here are NOT comparable to the report
  until the family-sweep records land (planned: clone the task, vary
  `constraints.json` per family).

File naming: `lns_mac_001_<provider>[_runN].json`.

## Records

- **`lns_mac_001_recipe_smoke.json`** (2026-07-14, pre-`model_id` code, so no
  per-event model tags; providers were `recipe,ollama` but every proposal came
  from the recipe library). Finding: the probe derived
  `throughput_target=3434` at 0 tokens; both recipe proposals
  (ARRAY_PARTITION on each input) grew the design (LUT 89,773 → 97,030) for a
  ~1% latency gain and `satisfice_then_area` correctly REJECTED both.
  Observation for the paper: the recipe library is monotone toward MORE
  parallelism — on an already-over-parallelized artifact the needed direction
  (relax the top `PIPELINE`) is one only the LLM can propose, and the
  recipe-first provider order never let it speak. LLM-only runs follow.

- **`lns_mac_001_ollama_run1.json`** (2026-07-14, LLM-only, per-event model
  tags live: `qwen3.6:35b-a3b-q4_K_M`). **Headline result.** In ONE local-LLM
  call the model diagnosed the over-parallelization and moved the top-level
  `#pragma HLS PIPELINE` to the inner j-loop as `PIPELINE II=1`:

  | | baseline | cand_0001 | |
  |---|---|---|---|
  | csynth | timing_fail, over capacity | **PASS** | fits + meets timing |
  | LUT | 89,773 (168.7%) | **21,013 (39.5%)** | 4.3× smaller |
  | latency (worst) | 3,433 | **2,073** | 40% faster |
  | FF | 43,198 | **8,027** | 5.4× fewer |
  | est. clock | 10.104 ns | **9.897 ns** | Fmax 98.97 → 101.04 MHz |

  Correctness re-verified: the 10k-trial golden-model csim passes on the
  edited design. The archived 2024 design goes from does-not-fit-and-fails-
  timing on xc7z020 to fits-meets-timing-and-40%-faster via one $0 LLM call —
  smaller AND faster, i.e. the baseline pragma wasn't buying speed, only area.
