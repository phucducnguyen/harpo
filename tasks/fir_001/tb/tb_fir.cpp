#include "fir.h"
#include <cstdio>

// Self-checking testbench: prints "TEST PASSED" + returns 0 on success, else
// prints MISMATCH lines and returns non-zero (the csim contract HARPO reads).
int main() {
  static int in[IN_SIZE];
  static int out[OUT_SIZE];
  static const int coef[TAPS] = {1, 2, 3, 4, 4, 3, 2, 1};

  for (int i = 0; i < IN_SIZE; i++) in[i] = (i % 11) - 5;

  fir(in, out);

  int errors = 0;
  for (int i = 0; i < OUT_SIZE; i++) {
    int expected = 0;
    for (int t = 0; t < TAPS; t++) expected += coef[t] * in[i + t];
    if (out[i] != expected) {
      errors++;
      if (errors <= 5)
        printf("MISMATCH at %d: got %d expected %d\n", i, out[i], expected);
    }
  }

  if (errors == 0) {
    printf("TEST PASSED\n");
    return 0;
  }
  printf("TEST FAILED: %d errors\n", errors);
  return 1;
}
