#ifndef FIR_H
#define FIR_H

// Fixed-size integer FIR filter: out[i] = sum_{t=0..TAPS-1} coef[t] * in[i+t].
// OUT_SIZE (128) is > the default Vitis HLS auto-pipeline threshold (64), so the
// outer loop is NOT auto-pipelined — leaving real headroom for an explicit
// #pragma HLS PIPELINE II=1 (plus ARRAY_PARTITION on `in` so the 8 taps can be
// read in one cycle). That makes the optimization measurable.
#define TAPS 8
#define OUT_SIZE 128
#define IN_SIZE (OUT_SIZE + TAPS - 1)

void fir(const int in[IN_SIZE], int out[OUT_SIZE]);

#endif // FIR_H
