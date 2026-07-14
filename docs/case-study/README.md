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
- **Scope caveat:** the 2024 report's tables sweep Artix/Kintex/Virtex. This
  Vitis install carries only the Zynq families (`list_part`: zynq,
  zynquplus, RFSoC variants), so `lns_mac_001_family_sweep.json` covers
  xc7z020 (Zynq-7000, Artix-class fabric) and xczu9eg (the upstream repo's
  own MAC target); its Virtex-7 rows record "Part is not installed" as
  honest evidence of the gap. Reproducing the report's exact family list
  requires adding device support to the install first.

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
  The winning source is preserved verbatim as
  `lns_mac_001_ollama_run1_winner.mac.cpp` (the run logs record events, not
  file contents — without this file the accepted design would live only in
  the gitignored `runs/`).

- **`lns_mac_001_ollama_run2.json` / `_run3.json`** (2026-07-14, LLM-only
  repeats of run 1, model tags in evidence). **Reproducibility: 3/3.** All
  three independent runs produced the SAME diagnosis, the SAME one-line
  pragma relocation, and bit-identical synthesis results (LUT 21,013,
  latency 2,073, timing met). The fix is not a lucky sample.

- **`lns_mac_001_family_sweep.json`** (2026-07-14, `scripts/family_sweep.py`,
  deterministic — no LLM). Baseline vs the run-1 fixed design across
  installed parts:

  | part | baseline | fixed |
  |---|---|---|
  | xc7z020 (Zynq-7000) | timing_fail, LUT 168.7% | pass, LUT 39.5%, lat 2,073 |
  | xczu9eg (upstream's own target) | pass, LUT 88,534 (32.3%), lat 2,138 | pass, LUT **21,231 (7.7%)**, lat **1,985** |

  Cross-family reading: on the small part the 2024 pragma breaks the design
  outright; on the large part it "works" — which is why the report's numbers
  looked fine — while silently spending **4.2×** the LUTs for a design that
  is also ~7% slower than the fix. Virtex-7 rows record "Part is not
  installed" (see scope caveat above).
