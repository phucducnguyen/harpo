#include "bicg.h"
#include <cstdio>

// Self-checking testbench: prints "TEST PASSED" + returns 0 on success, else
// prints MISMATCH lines and returns non-zero (the csim contract HARPO reads).
int main() {
  static int A[N * M];
  static int p[M];
  static int r[N];
  static int s[M];
  static int q[N];
  static int s_ref[M];
  static int q_ref[N];

  // Small deterministic inputs (entries 0..3) to keep the MACs well within int
  // range at N=M=16.
  for (int i = 0; i < N * M; i++) A[i] = i % 4;
  for (int j = 0; j < M; j++) p[j] = (j + 1) % 4;
  for (int i = 0; i < N; i++) r[i] = (i * 2 + 1) % 4;

  // Host reference: s_ref = A^T * r, q_ref = A * p, same fused formula.
  for (int j = 0; j < M; j++) s_ref[j] = 0;
  for (int i = 0; i < N; i++) {
    q_ref[i] = 0;
    for (int j = 0; j < M; j++) {
      s_ref[j] += A[i * M + j] * r[i];
      q_ref[i] += A[i * M + j] * p[j];
    }
  }

  bicg(A, p, r, s, q);

  int errors = 0;
  for (int j = 0; j < M; j++) {
    if (s[j] != s_ref[j]) {
      errors++;
      if (errors <= 5)
        printf("MISMATCH at s(%d): got %d expected %d\n", j, s[j], s_ref[j]);
    }
  }
  for (int i = 0; i < N; i++) {
    if (q[i] != q_ref[i]) {
      errors++;
      if (errors <= 5)
        printf("MISMATCH at q(%d): got %d expected %d\n", i, q[i], q_ref[i]);
    }
  }

  if (errors == 0) {
    printf("TEST PASSED\n");
    return 0;
  }
  printf("TEST FAILED: %d errors\n", errors);
  return 1;
}
