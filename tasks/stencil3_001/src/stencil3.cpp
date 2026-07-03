#include "stencil3.h"

// Baseline: correct but unoptimized. The outer loop has no pipeline pragma and
// (trip 256 > threshold) is not auto-pipelined, so each output is produced
// sequentially. `in` is a single-port memory, so the three reads per iteration
// serialize. Cyclic-partitioning `in` (factor 4) + `#pragma HLS PIPELINE` on
// the loop gives parallel reads and overlaps iterations -> large latency
// reduction with no change to the computed result.
void stencil3(const int in[IN_SIZE], int out[OUT_SIZE]) {
  for (int i = 0; i < OUT_SIZE; i++) {
    out[i] = in[i] + in[i + 1] + in[i + 2];
  }
}
