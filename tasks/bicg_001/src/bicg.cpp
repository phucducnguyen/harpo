#include "bicg.h"

// Baseline: correct but unoptimized PolyBench-style integer bicg. Computes, in
// one fused pass over the NxM row-major matrix A:
//   s = A^T * r   (length M)
//   q = A   * p   (length N)
// s is zeroed first, then both accumulations run inside the same i/j nest. The
// inner j-loop (the multiply-accumulate over a row of A) runs sequentially with
// no pipeline pragma, so each update is produced one MAC at a time. Adding
// `#pragma HLS PIPELINE II=1` to the inner loop and partitioning A/p lets the
// accumulate overlap iterations -> large latency reduction with no change to the
// computed result.
void bicg(const int A[N * M], const int p[M], const int r[N], int s[M], int q[N]) {
  for (int j = 0; j < M; j++) {
    s[j] = 0;
  }
  for (int i = 0; i < N; i++) {
    q[i] = 0;
    for (int j = 0; j < M; j++) {
      s[j] += A[i * M + j] * r[i];
      q[i] += A[i * M + j] * p[j];
    }
  }
}
