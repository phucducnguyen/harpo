#ifndef GEMM_H
#define GEMM_H

// PolyBench-style fixed-size integer GEMM: C = beta*C + alpha*(A*B), all NxN,
// row-major flat arrays. N is kept modest (16) so csynth completes quickly
// later, while the triple loop plus the scaling is canonical enough to exercise
// the optimizer's generalization. alpha/beta are small integer constants to keep
// values exact and DSP usage low (no double/float). The innermost
// multiply-accumulate k-loop runs sequentially in the baseline, leaving real PPA
// headroom: pipelining the inner loop and partitioning B's row dimension
// parallelizes the dot-products -> large latency drop with no change to the
// computed result.
#define N 16

#define ALPHA 2
#define BETA 3

void gemm(const int A[N * N], const int B[N * N], int C[N * N]);

#endif
