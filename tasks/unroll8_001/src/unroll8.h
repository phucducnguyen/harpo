#ifndef UNROLL8_H
#define UNROLL8_H

// Fixed-size kernel with a 16-wide inner reduction:
//   out[i] = sum_{k=0..15} (in[i*K + k] << (k & 3))
// The inner k-loop is a fixed small trip count whose shift-accumulates are
// independent enough to parallelize. Fully unrolling the inner loop is the
// measurable win. OUT_SIZE > the auto-pipeline threshold so the outer loop is
// real work; IN_SIZE = OUT_SIZE * K.
#define K 16
#define OUT_SIZE 128
#define IN_SIZE (OUT_SIZE * K)

void unroll8(const int in[IN_SIZE], int out[OUT_SIZE]);

#endif
