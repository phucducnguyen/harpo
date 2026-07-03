#ifndef BICG_H
#define BICG_H

// PolyBench-style fixed-size integer bicg: the canonical fused BiCGStab kernel
// sub-pass computing s = A^T * r and q = A * p in a single pass over the NxM
// matrix A (row-major flat array). N and M are kept modest (16) so csynth
// completes quickly later, while the doubly-nested accumulate is canonical
// enough to exercise the optimizer's generalization. All values are small
// integers to keep results exact and DSP usage low (no double/float). The inner
// j-loop runs sequentially in the baseline, leaving real PPA headroom:
// pipelining the inner loop and partitioning A/p parallelizes the
// multiply-accumulates -> large latency drop with no change to the computed
// result.
#define N 16
#define M 16

void bicg(const int A[N * M], const int p[M], const int r[N], int s[M], int q[N]);

#endif
