#include "mac8.h"
#include <cstdio>

// Self-checking testbench: prints "TEST PASSED" + returns 0 on success, else
// prints MISMATCH lines and returns non-zero (the csim contract HARPO reads).
int main() {
  static int in[IN_SIZE];
  static int out[OUT_SIZE];

  for (int i = 0; i < IN_SIZE; i++) in[i] = (i % 7) - 3;

  mac8(in, out);

  int errors = 0;
  for (int i = 0; i < OUT_SIZE; i++) {
    int expected = 0;
    for (int k = 0; k < 8; k++) expected += in[i * 8 + k];
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
