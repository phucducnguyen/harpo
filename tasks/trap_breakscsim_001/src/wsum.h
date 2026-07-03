#ifndef WSUM_H
#define WSUM_H

// Fixed-size windowed sum: OUT_SIZE outputs, each the sum of WINDOW inputs.
// Correct-but-unoptimized baseline (csim PASSES). OUT_SIZE is > the default
// Vitis HLS auto-pipeline threshold (64), so the outer loop is NOT
// auto-pipelined — leaving real headroom for an explicit #pragma HLS PIPELINE.
//
// This is the CORRECTNESS-TRAP fixture: the accompanying mock_patch.json is a
// genuine C++ semantic change (drops the last accumulation term) that a naive
// optimizer might mistake for a speed-up but that produces WRONG output under a
// real g++ csim. The optimize loop MUST re-verify csim, see the regression, and
// discard the broken child — keeping the correct baseline.
#define OUT_SIZE 128
#define WINDOW 4
#define IN_SIZE (OUT_SIZE * WINDOW)

void wsum(const int in[IN_SIZE], int out[OUT_SIZE]);

#endif
