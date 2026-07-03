#ifndef ATAX_H
#define ATAX_H

// PolyBench-style fixed-size integer ATAX: y = A^T * (A * x), all sizes fixed,
// row-major flat arrays. A is M x N, x is length N, y is length N; the
// intermediate tmp (length M) holds A*x. M and N are kept modest (16) so csynth
// completes quickly later, while the two-phase structure (a row reduction
// feeding a transposed accumulate) is canonical enough to exercise the
// optimizer's generalization beyond a single dot-product. Both inner loops run
// sequentially in the baseline, leaving real PPA headroom: pipelining the inner
// loops and partitioning A/x parallelizes the multiply-accumulate -> large
// latency drop with no change to the computed result.
#define M 16
#define N 16

void atax(const int A[M * N], const int x[N], int y[N]);

#endif
