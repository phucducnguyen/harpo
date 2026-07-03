#ifndef STENCIL3_H
#define STENCIL3_H

// Fixed-size 1-D 3-tap stencil: out[i] = in[i] + in[i+1] + in[i+2].
// OUT_SIZE is > the default Vitis HLS auto-pipeline threshold (64), so the
// outer loop is NOT auto-pipelined — leaving real headroom for an explicit
// #pragma HLS PIPELINE. IN_SIZE = OUT_SIZE + 2 so the last window fits.
#define OUT_SIZE 256
#define IN_SIZE (OUT_SIZE + 2)

void stencil3(const int in[IN_SIZE], int out[OUT_SIZE]);

#endif
