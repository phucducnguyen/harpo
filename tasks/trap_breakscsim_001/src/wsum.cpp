#include "wsum.h"

// Baseline: correct but unoptimized. The outer loop has no pipeline pragma and
// (trip 128 > threshold) is not auto-pipelined, so each output is produced
// sequentially. A correctness-preserving optimization (e.g. #pragma HLS
// PIPELINE on the outer loop) would cut latency without changing results.
//
// The TRAP patch (mock_patch.json) instead rewrites the inner-loop bound from
// `k < WINDOW` to `k < WINDOW - 1`, dropping the last term of every window. That
// is faster to "execute" but functionally WRONG — g++ runs it and the testbench
// reports MISMATCH. The optimize loop's csim re-verify catches it.
void wsum(const int in[IN_SIZE], int out[OUT_SIZE]) {
  for (int i = 0; i < OUT_SIZE; i++) {
    int acc = 0;
    for (int k = 0; k < WINDOW; k++) {
      acc += in[i * WINDOW + k];
    }
    out[i] = acc;
  }
}
