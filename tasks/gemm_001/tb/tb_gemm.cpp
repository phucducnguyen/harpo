#include "gemm.h"
#include <cstdio>

// Self-checking testbench: prints "TEST PASSED" + returns 0 on success, else
// prints MISMATCH lines and returns non-zero (the csim contract HARPO reads).
int main() {
  static int A[N * N];
  static int B[N * N];
  static int C[N * N];
  static int C_ref[N * N];

  for (int i = 0; i < N * N; i++) A[i] = i % 7;
  for (int i = 0; i < N * N; i++) B[i] = (i * 3 + 1) % 5;
  for (int i = 0; i < N * N; i++) {
    C[i] = (i * 2 + 4) % 6;
    C_ref[i] = C[i];
  }

  // Host reference: C_ref = beta*C + alpha*(A*B), computed before the kernel
  // overwrites C in place.
  for (int i = 0; i < N; i++) {
    for (int j = 0; j < N; j++) {
      int acc = 0;
      for (int k = 0; k < N; k++) acc += A[i * N + k] * B[k * N + j];
      C_ref[i * N + j] = BETA * C_ref[i * N + j] + ALPHA * acc;
    }
  }

  gemm(A, B, C);

  int errors = 0;
  for (int i = 0; i < N; i++) {
    for (int j = 0; j < N; j++) {
      int expected = C_ref[i * N + j];
      int got = C[i * N + j];
      if (got != expected) {
        errors++;
        if (errors <= 5)
          printf("MISMATCH at (%d,%d): got %d expected %d\n", i, j, got, expected);
      }
    }
  }

  if (errors == 0) {
    printf("TEST PASSED\n");
    return 0;
  }
  printf("TEST FAILED: %d errors\n", errors);
  return 1;
}
