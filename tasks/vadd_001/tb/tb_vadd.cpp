#include <cstdio>
#include "vadd.h"

#define N 1024

// Public testbench. Returns 0 on PASS, non-zero on FAIL — Vitis HLS uses the
// return code to mark csim pass/fail. The agent must NOT modify this file.
int main() {
  int a[N], b[N], c[N], gold[N];

  for (int i = 0; i < N; i++) {
    a[i]    = i;
    b[i]    = 2 * i;
    gold[i] = a[i] + b[i];
    c[i]    = 0;
  }

  vadd(a, b, c, N);

  int errors = 0;
  for (int i = 0; i < N; i++) {
    if (c[i] != gold[i]) {
      if (errors < 10)
        printf("MISMATCH at %d: expected %d got %d\n", i, gold[i], c[i]);
      errors++;
    }
  }

  if (errors == 0) {
    printf("TEST PASSED\n");
    return 0;
  }
  printf("TEST FAILED: %d mismatches\n", errors);
  return 1;
}
