#include "unroll8.h"

// Baseline: correct but unoptimized. The inner k-loop (fixed trip K=16) runs
// sequentially — one shift-accumulate per cycle — so each output costs ~K
// iterations. The shifts are data-independent across k, so fully unrolling the
// inner loop lets them compute in parallel (adder tree) -> large latency
// reduction with no change to the computed result. The outer loop drives
// OUT_SIZE outputs.
void unroll8(const int in[IN_SIZE], int out[OUT_SIZE]) {
  for (int i = 0; i < OUT_SIZE; i++) {
    int acc = 0;
    for (int k = 0; k < K; k++) {
      acc += in[i * K + k] << (k & 3);
    }
    out[i] = acc;
  }
}
