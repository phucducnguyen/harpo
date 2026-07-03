#include "scale.h"

// BUGGY on purpose — repair target. Wrong operator: '+' should be '*'. The
// kernel scales each element by k, but the planted bug adds k instead, so csim
// FAILS with a clean, deterministic mismatch. Interface/signature are correct,
// so the fix is a one-character functional patch. The agent must preserve the
// signature and testbench and only edit the loop body.
void scale(const int *in, int *out, int k, int n) {
#pragma HLS INTERFACE m_axi port=in bundle=gmem0 offset=slave
#pragma HLS INTERFACE m_axi port=out bundle=gmem1 offset=slave
#pragma HLS INTERFACE s_axilite port=in bundle=control
#pragma HLS INTERFACE s_axilite port=out bundle=control
#pragma HLS INTERFACE s_axilite port=k bundle=control
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control

  for (int i = 0; i < n; i++) {
    out[i] = in[i] + k;   // BUG: should be in[i] * k
  }
}
