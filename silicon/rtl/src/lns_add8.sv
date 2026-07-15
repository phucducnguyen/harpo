// Combinational 8-way log-domain adder — the interesting block.
//
// Mirrors add_unit.cpp's adder(): bucket the 8 inputs by (sign x remainder),
// accumulate 2^(quotient+QBIAS) per bucket, apply the Mitchell 2^(r/8) scale,
// sum positive-minus-negative, and convert the fixed-point result back to LNS.
// All four stages are the shared lns_pkg functions, so this reference and the
// pipelined lns_mac8 are bit-identical by construction.
//
// Inputs are the 8 PRODUCTS (post-multiply LNS elements), matching the C
// adder() signature, packed low-index-first: input[i] = prods[i*16 +: 16].
// Purely combinational so the bench can check it against the C adder() directly.

module lns_add8
  import lns_pkg::*;
(
  input  logic [NLEN*16-1:0] prods,
  output logic [15:0]        sum
);
  logic [M*20-1:0]    buckets;
  logic [M*32-1:0]    scaled;
  logic signed [35:0] acc;

  assign buckets = build_buckets(prods);
  assign scaled  = scale_buckets(buckets);
  assign acc     = reduce_buckets(scaled);
  assign sum     = convertback_f(acc);
endmodule
