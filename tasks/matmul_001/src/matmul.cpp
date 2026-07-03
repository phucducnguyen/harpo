#include "matmul.h"

// Baseline: correct but unoptimized NxN integer matrix multiply, C = A * B.
// Row-major flat arrays. The innermost k-loop (the dot-product accumulate) runs
// sequentially with no pipeline pragma, so each output element is produced one
// MAC at a time. Adding `#pragma HLS PIPELINE II=1` to the inner loop and
// cyclically partitioning B lets the accumulate overlap iterations -> large
// latency reduction with no change to the computed result.
void matmul(const int A[N * N], const int B[N * N], int C[N * N]) {
  for (int i = 0; i < N; i++) {
    for (int j = 0; j < N; j++) {
      int acc = 0;
      for (int k = 0; k < N; k++) {
        acc += A[i * N + k] * B[k * N + j];
      }
      C[i * N + j] = acc;
    }
  }
}
