#ifndef CONV2D_H
#define CONV2D_H

// Fixed-size integer 2-D "valid" convolution: out = in (*) ker.
// Input is IH x IW, kernel is K x K, output is OH x OW with OH=IH-K+1,
// OW=IW-K+1 (valid convolution, no padding). All row-major flat int arrays.
// Sizes are kept modest (8x8 input, 3x3 kernel -> 6x6 output) so csynth
// completes quickly later, while the 4-nested loop is canonical enough to
// exercise the optimizer's generalization beyond 1-D reductions and the matmul
// triple loop. The innermost accumulate runs sequentially in the baseline,
// leaving real PPA headroom: pipelining the inner loop and completely
// partitioning the tiny kernel array parallelizes the multiply-accumulate ->
// large latency drop with no change to the computed result.
#define IH 8
#define IW 8
#define K 3
#define OH (IH - K + 1)
#define OW (IW - K + 1)

void conv2d(const int in[IH * IW], const int ker[K * K], int out[OH * OW]);

#endif
