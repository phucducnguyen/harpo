#include "fir.h"

// Baseline: correct but unoptimized. The outer loop has no pipeline pragma and
// (trip 128 > threshold) is not auto-pipelined, so each output is produced
// sequentially over a single-port `in` memory. Adding ARRAY_PARTITION on `in`
// plus `#pragma HLS PIPELINE II=1` on the outer loop lets the 8 tap reads and
// multiply-accumulates overlap -> large latency reduction (and DSP-backed
// multiplies) with no change to the computed result.
void fir(const int in[IN_SIZE], int out[OUT_SIZE]) {
  static const int coef[TAPS] = {1, 2, 3, 4, 4, 3, 2, 1};

  for (int i = 0; i < OUT_SIZE; i++) {
    int acc = 0;
    for (int t = 0; t < TAPS; t++) {
      acc += coef[t] * in[i + t];
    }
    out[i] = acc;
  }
}
