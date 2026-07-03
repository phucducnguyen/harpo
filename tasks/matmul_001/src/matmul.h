#ifndef MATMUL_H
#define MATMUL_H

// Fixed-size integer matrix multiply: C = A * B, all NxN, row-major flat arrays.
// N is kept modest (8) so csynth completes quickly later, while the triple loop
// is canonical enough to exercise the optimizer's generalization beyond 1-D
// reductions. The inner multiply-accumulate loop runs sequentially in the
// baseline, leaving real PPA headroom: pipelining the inner loop and
// partitioning B's row dimension parallelizes the dot-products -> large latency
// drop with no change to the computed result.
#define N 8

void matmul(const int A[N * N], const int B[N * N], int C[N * N]);

#endif
