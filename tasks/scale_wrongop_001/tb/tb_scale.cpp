#include "scale.h"
#include <cstdio>

#define N 1024

// Self-checking testbench — do NOT modify. With the buggy kernel (+ instead of
// *) this returns non-zero (csim FAIL); after repair it must return 0. out[] is
// sentinel-initialized to 0 and the golden compares all N elements.
int main() {
  int in[N], out[N], gold[N];
  const int k = 5;

  for (int i = 0; i < N; i++) {
    in[i]   = (i % 13) - 6;
    gold[i] = in[i] * k;
    out[i]  = 0;
  }

  scale(in, out, k, N);

  int errors = 0;
  for (int i = 0; i < N; i++) {
    if (out[i] != gold[i]) {
      if (errors < 10)
        printf("MISMATCH at %d: expected %d got %d\n", i, gold[i], out[i]);
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
