#include <cstdio>
#include "../src/vadd.h"

#define N 1024

// Same public testbench as vadd_001 — do NOT modify. With the buggy kernel
// this returns non-zero (csim FAIL); after repair it must return 0.
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
