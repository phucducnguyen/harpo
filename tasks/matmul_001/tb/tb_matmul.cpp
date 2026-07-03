#include "matmul.h"
#include <cstdio>

// Self-checking testbench: prints "TEST PASSED" + returns 0 on success, else
// prints MISMATCH lines and returns non-zero (the csim contract HARPO reads).
int main() {
  static int A[N * N];
  static int B[N * N];
  static int C[N * N];

  for (int i = 0; i < N * N; i++) A[i] = i % 7;
  for (int i = 0; i < N * N; i++) B[i] = (i * 3 + 1) % 5;

  matmul(A, B, C);

  int errors = 0;
  for (int i = 0; i < N; i++) {
    for (int j = 0; j < N; j++) {
      int expected = 0;
      for (int k = 0; k < N; k++) expected += A[i * N + k] * B[k * N + j];
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
