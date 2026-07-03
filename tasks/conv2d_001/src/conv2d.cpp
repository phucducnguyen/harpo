#include "conv2d.h"

// Baseline: correct but unoptimized fixed-size integer 2-D "valid" convolution,
// out = in (*) ker. Row-major flat arrays. For each output pixel (oy,ox) the
// inner ky/kx loops accumulate the elementwise product of the KxK kernel with
// the overlapping input window. The innermost accumulate runs sequentially with
// no pipeline pragma. Adding `#pragma HLS PIPELINE II=1` to the inner loop and
// completely partitioning the small kernel array lets the accumulate overlap
// iterations -> large latency reduction with no change to the computed result.
void conv2d(const int in[IH * IW], const int ker[K * K], int out[OH * OW]) {
  for (int oy = 0; oy < OH; oy++) {
    for (int ox = 0; ox < OW; ox++) {
      int acc = 0;
      for (int ky = 0; ky < K; ky++) {
        for (int kx = 0; kx < K; kx++) {
          acc += in[(oy + ky) * IW + (ox + kx)] * ker[ky * K + kx];
        }
      }
      out[oy * OW + ox] = acc;
    }
  }
}
