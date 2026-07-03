| Kernel | Category | TargetSource | Target | Method | Correct | interval_max | latency | LUT | FF | BRAM | DSP | area_score | ADP | ToolCalls | Tokens | Accepted | Reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mac8_001 | hand-built | — | — | baseline | ✓ | 1024 | 1026 | 369 | 153 | 0 | 0 | 0.008374 | 8.57504 | — | — | — | — |
| mac8_001 | hand-built | hand-set | 256 | recipe (satisfice_then_area) | ✓ | 256 | 259 | 315 | 126 | 0 | 0 | 0.007105 | 1.81895 | 11 | 0 | ✓ | meets target, lowest area |
| mac8_001 | hand-built | hand-set | 256 | raw LLM | ✓ | 1024 | 1026 | 369 | 153 | 0 | 0 | 0.008374 | 8.57504 | 8 | 7207 | ✗ | no improvement, baseline kept |
| stencil3_001 | hand-built | — | — | baseline | ✓ | 512 | 514 | 193 | 95 | 0 | 0 | 0.004521 | 2.31459 | — | — | — | — |
| stencil3_001 | hand-built | hand-set | 257 | recipe (satisfice_then_area) | ✓ | 257 | 259 | 435 | 43 | 0 | 0 | 0.008581 | 2.20527 | 14 | 0 | ✓ | meets target, lowest area |
| unroll8_001 | hand-built | — | — | baseline | ✓ | 1024 | 1026 | 727 | 451 | 0 | 0 | 0.0179 | 18.3338 | — | — | — | — |
| unroll8_001 | hand-built | hand-set | 128 | recipe (satisfice_then_area) | ✓ | 128 | 132 | 597 | 368 | 0 | 0 | 0.01468 | 1.8791 | 11 | 0 | ✓ | meets target, lowest area |
| matmul_001 | hand-built | — | — | baseline | ✓ | 256 | 260 | 706 | 579 | 0 | 6 | 0.04599 | 11.7722 | — | — | — | — |
| matmul_001 | hand-built | hand-set | 72 | recipe (satisfice_then_area) | ✓ | 44 | 43 | 3121 | 5932 | 0 | 48 | 0.3326 | 14.6344 | 14 | 0 | ✓ | meets target, lowest area |
| matmul_001 | hand-built | n/a | — | recipe (speed_first) | ✓ | 19 | 18 | 5689 | 14999 | 0 | 192 | 1.121 | 21.292 | 17 | 0 | ✓ | kept best |
| matmul_001 | hand-built | hand-set | 72 | raw LLM | ✓ | 256 | 260 | 706 | 579 | 0 | 6 | 0.04599 | 11.7722 | 8 | 17106 | ✗ | no improvement, baseline kept |
| conv2d_001 | hand-built | — | — | baseline | ✓ | 191 | 190 | 871 | 903 | 0 | 6 | 0.05213 | 9.95716 | — | — | — | — |
| conv2d_001 | hand-built | hand-set | 85 | recipe (satisfice_then_area) | ✓ | 82 | 81 | 1318 | 2277 | 0 | 15 | 0.1144 | 9.37724 | 17 | 0 | ✓ | meets target, lowest area |
| gemm_001 | PolyBench | — | — | baseline | ✓ | 2060 | 2054 | 1238 | 1180 | 0 | 6 | 0.06163 | 126.965 | — | — | — | — |
| gemm_001 | PolyBench | fallback | 2060 | recipe (satisfice_then_area) | ✓ | 2060 | 2054 | 1238 | 1180 | 0 | 6 | 0.06163 | 126.965 | 18 | 0 | ✗ | no improvement, baseline kept |
| gemm_001 | PolyBench | fallback | 2060 | raw LLM | ✓ | 2060 | 2054 | 1238 | 1180 | 0 | 6 | 0.06163 | 126.965 | 18 | 14192 | ✗ | no improvement, baseline kept |
| atax_001 | PolyBench | — | — | baseline | ✓ | 304 | 303 | 2481 | 2492 | 0 | 6 | 0.09733 | 29.5881 | — | — | — | — |
| atax_001 | PolyBench | auto-derived | 280 | recipe (satisfice_then_area) | ✓ | 64 | 63 | 3907 | 5596 | 0 | 48 | 0.3442 | 22.0298 | 23 | 0 | ✓ | meets target, lowest area |
| atax_001 | PolyBench | auto-derived | 280 | raw LLM | ✓ | 81 | 80 | 3994 | 5591 | 0 | 48 | 0.3458 | 28.0101 | 23 | 23535 | ✓ | meets target, lowest area |
| bicg_001 | PolyBench | — | — | baseline | ✓ | 171 | 170 | 2169 | 2640 | 0 | 12 | 0.1201 | 20.5419 | — | — | — | — |
| bicg_001 | PolyBench | auto-derived | 162 | recipe (satisfice_then_area) | ✓ | 60 | 59 | 3596 | 8929 | 0 | 96 | 0.5879 | 35.2726 | 23 | 0 | ✓ | meets target, lowest area |
