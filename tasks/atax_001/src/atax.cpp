#include "atax.h"

// Baseline: correct but unoptimized PolyBench-style integer ATAX,
// y = A^T * (A * x). Row-major flat arrays. tmp (length M) is a local array
// holding the first product A*x; y (length N) is zeroed, then accumulated with
// A^T * tmp. Both inner loops (the dot-product accumulate and the transposed
// accumulate) run sequentially with no pipeline pragma, so each element is
// produced one MAC at a time. Adding `#pragma HLS PIPELINE II=1` to the inner
// loops and partitioning A/x lets the accumulate overlap iterations -> large
// latency reduction with no change to the computed result.
void atax(const int A[M * N], const int x[N], int y[N]) {
  int tmp[M];

  // Step 1: tmp = A * x  (per-row dot product over j).
  for (int i = 0; i < M; i++) {
    int acc = 0;
    for (int j = 0; j < N; j++) {
      acc += A[i * N + j] * x[j];
    }
    tmp[i] = acc;
  }

  // Step 2: y = A^T * tmp  (zero y, then accumulate column-wise).
  for (int j = 0; j < N; j++) {
    y[j] = 0;
  }
  for (int i = 0; i < M; i++) {
    for (int j = 0; j < N; j++) {
      y[j] += A[i * N + j] * tmp[i];
    }
  }
}
