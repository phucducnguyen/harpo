#include "wsum.h"
#include <cstdio>

// Self-checking testbench: prints "TEST PASSED" + returns 0 on success, else
// prints MISMATCH lines and returns non-zero (the csim contract HARPO reads).
// The golden result is computed INDEPENDENTLY of the kernel — full WINDOW-wide
// sums — so any dropped/altered term in the kernel surfaces as a MISMATCH.
int main() {
  static int in[IN_SIZE];
  static int out[OUT_SIZE];

  // Non-trivial, all-nonzero inputs so dropping the last window term always
  // changes the result (every in[*] != 0 -> the trap is never masked).
  for (int i = 0; i < IN_SIZE; i++) in[i] = (i % 9) + 1;

  wsum(in, out);

  int errors = 0;
  for (int i = 0; i < OUT_SIZE; i++) {
    int expected = 0;
    for (int k = 0; k < WINDOW; k++) expected += in[i * WINDOW + k];
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
