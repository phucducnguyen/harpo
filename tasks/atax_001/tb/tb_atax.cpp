#include "atax.h"
#include <cstdio>

// Self-checking testbench: prints "TEST PASSED" + returns 0 on success, else
// prints MISMATCH lines and returns non-zero (the csim contract HARPO reads).
// Values are kept small (A in 0..3, x in 0..3, M=N=16) so every accumulate stays
// well within int: tmp[i] <= 16*3*3 = 144, y[j] <= 16*3*144 = 6912.
int main() {
  static int A[M * N];
  static int x[N];
  static int y[N];
  static int y_ref[N];
  static int tmp_ref[M];

  for (int i = 0; i < M * N; i++) A[i] = i % 4;   // 0..3
  for (int i = 0; i < N; i++) x[i] = (i * 2 + 1) % 4;  // 0..3

  // Host reference: y_ref = A^T * (A * x), same formula as the kernel.
  for (int i = 0; i < M; i++) {
    int acc = 0;
    for (int j = 0; j < N; j++) acc += A[i * N + j] * x[j];
    tmp_ref[i] = acc;
  }
  for (int j = 0; j < N; j++) y_ref[j] = 0;
  for (int i = 0; i < M; i++) {
    for (int j = 0; j < N; j++) y_ref[j] += A[i * N + j] * tmp_ref[i];
  }

  atax(A, x, y);

  int errors = 0;
  for (int j = 0; j < N; j++) {
    int expected = y_ref[j];
    int got = y[j];
    if (got != expected) {
      errors++;
      if (errors <= 5)
        printf("MISMATCH at (%d): got %d expected %d\n", j, got, expected);
    }
  }

  if (errors == 0) {
    printf("TEST PASSED\n");
    return 0;
  }
  printf("TEST FAILED: %d errors\n", errors);
  return 1;
}
