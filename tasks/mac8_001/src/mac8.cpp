#include "mac8.h"

// Baseline: correct but unoptimized. The outer loop has no pipeline pragma and
// (trip 256 > threshold) is not auto-pipelined, so each output is produced
// sequentially. Adding `#pragma HLS PIPELINE` to the outer loop lets the inner
// accumulate unroll and overlaps iterations -> large latency reduction with no
// change to the computed result.
void mac8(const int in[IN_SIZE], int out[OUT_SIZE]) {
  for (int i = 0; i < OUT_SIZE; i++) {
    int acc = 0;
    for (int k = 0; k < 8; k++) {
      acc += in[i * 8 + k];
    }
    out[i] = acc;
  }
}
