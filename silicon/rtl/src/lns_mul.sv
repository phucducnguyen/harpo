// Combinational LNS multiply (one element x one element).
//
// Kept as a thin wrapper over lns_pkg::lns_mul_f so the multiply lives in one
// place. Ports are flat 16-bit words (not the struct) so the cocotb bench can
// drive/read them as plain integers without depending on simulator struct
// support. Latency: 0 cycles; instantiated 8-wide inside lns_mac8.

module lns_mul
  import lns_pkg::*;
(
  input  logic [15:0] a,
  input  logic [15:0] b,
  output logic [15:0] p
);
  assign p = lns_mul_f(lns_t'(a), lns_t'(b));
endmodule
