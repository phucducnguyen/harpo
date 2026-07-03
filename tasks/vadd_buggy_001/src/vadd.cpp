#include "vadd.h"

// BUGGY on purpose — first repair target (Week 3). Wrong operator: '-' should
// be '+'. csim FAILS with a clean, deterministic mismatch; interface/signature
// are correct, so the fix is a one-character functional patch. The agent must
// preserve the signature and testbench and only edit the loop body.
void vadd(const int *a, const int *b, int *c, int n) {
#pragma HLS INTERFACE m_axi port=a bundle=gmem0 offset=slave
#pragma HLS INTERFACE m_axi port=b bundle=gmem1 offset=slave
#pragma HLS INTERFACE m_axi port=c bundle=gmem2 offset=slave
#pragma HLS INTERFACE s_axilite port=a bundle=control
#pragma HLS INTERFACE s_axilite port=b bundle=control
#pragma HLS INTERFACE s_axilite port=c bundle=control
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control

  for (int i = 0; i < n; i++) {
    c[i] = a[i] - b[i];   // BUG: should be a[i] + b[i]
  }
}
