#include "vadd.h"

// BUGGY on purpose — repair target. Off-by-one loop bound: `i < n - 1` leaves
// the last element c[n-1] unwritten, so csim FAILS with a clean MISMATCH on the
// final index (the testbench sentinel-inits c[] to 0, so this is a deterministic
// compare failure, NOT out-of-bounds UB). The fix is `i < n`. The agent must
// preserve the signature and testbench and only edit the loop bound.
void vadd(const int *a, const int *b, int *c, int n) {
#pragma HLS INTERFACE m_axi port=a bundle=gmem0 offset=slave
#pragma HLS INTERFACE m_axi port=b bundle=gmem1 offset=slave
#pragma HLS INTERFACE m_axi port=c bundle=gmem2 offset=slave
#pragma HLS INTERFACE s_axilite port=a bundle=control
#pragma HLS INTERFACE s_axilite port=b bundle=control
#pragma HLS INTERFACE s_axilite port=c bundle=control
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control

  for (int i = 0; i < n - 1; i++) {   // BUG: should be i < n
    c[i] = a[i] + b[i];
  }
}
