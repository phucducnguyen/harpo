#ifndef MAC8_H
#define MAC8_H

// Fixed-size windowed sum: OUT_SIZE outputs, each the sum of 8 inputs.
// OUT_SIZE is > the default Vitis HLS auto-pipeline threshold (64), so the
// outer loop is NOT auto-pipelined — leaving real headroom for an explicit
// #pragma HLS PIPELINE. That makes the optimization measurable.
#define OUT_SIZE 256
#define IN_SIZE (OUT_SIZE * 8)

void mac8(const int in[IN_SIZE], int out[OUT_SIZE]);

#endif
