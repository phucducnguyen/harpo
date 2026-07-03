#include "conv2d.h"
#include <cstdio>

// Self-checking testbench: prints "TEST PASSED" + returns 0 on success, else
// prints MISMATCH lines and returns non-zero (the csim contract HARPO reads).
int main() {
  static int in[IH * IW];
  static int ker[K * K];
  static int out[OH * OW];

  for (int i = 0; i < IH * IW; i++) in[i] = i % 7;
  for (int i = 0; i < K * K; i++) ker[i] = (i % 3) + 1;

  conv2d(in, ker, out);

  int errors = 0;
  for (int oy = 0; oy < OH; oy++) {
    for (int ox = 0; ox < OW; ox++) {
      int expected = 0;
      for (int ky = 0; ky < K; ky++)
        for (int kx = 0; kx < K; kx++)
          expected += in[(oy + ky) * IW + (ox + kx)] * ker[ky * K + kx];
      int got = out[oy * OW + ox];
      if (got != expected) {
        errors++;
        if (errors <= 5)
          printf("MISMATCH at (%d,%d): got %d expected %d\n", oy, ox, got, expected);
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
