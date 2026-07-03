#include "vadd.h"

// Reference-correct vector add. Gate-0 target: this must csim PASS and
// csynth PASS on a clean Vitis HLS install. If it doesn't, the toolchain
// is the problem, not the kernel.
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
    c[i] = a[i] + b[i];
  }
}
