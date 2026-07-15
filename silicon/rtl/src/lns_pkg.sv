// LNS number-system parameters, element record, and the pure combinational
// datapath functions shared by every module below.
//
// This mirrors the C reference (tasks/lns_mac_001/src/{LNS_datatype,mul_unit,
// add_unit}.{h,cpp}) bit-for-bit. Keeping the arithmetic in ONE place — these
// package functions — is deliberate: the combinational reference modules
// (lns_mul, lns_add8) and the pipelined datapath (lns_mac8) both call the same
// functions, so they cannot drift apart. Where the C looks odd it is copied
// anyway and flagged: this is a fidelity exercise, not a redesign.
//
// Format (B=7, Q=4, R=3, Gamma=8): a value is +/- 2^(exponent/8) with
//   exponent = quotient*8 + remainder,  floored division so remainder >= 0.

package lns_pkg;

  localparam int unsigned B     = 7;    // signed total-exponent width
  localparam int unsigned Q     = 4;    // signed quotient width
  localparam int unsigned R     = 3;    // unsigned remainder width
  localparam int unsigned GAMMA = 8;    // log base
  localparam int unsigned NLEN  = 8;    // dot-product length / matrix dim
  localparam int unsigned M     = 16;   // partial-sum buckets = 2*GAMMA

  localparam int          QBIAS   = 8;
  localparam int          EXP_MIN = -64;  // -(QBIAS*GAMMA), encodes 2^-8
  localparam int          EXP_MAX = 63;   // (QBIAS-1)*GAMMA + (GAMMA-1)

  // 16-bit packed element. Field order below == bit order [15:0]:
  //   [15] sign  [14] zero  [13:7] exponent  [6:3] quotient  [2:0] remainder
  typedef struct packed {
    logic                sign;       // 1 = negative
    logic                zero;       // exact-zero flag (0 is not a 2^e value)
    logic signed [B-1:0] exponent;   // total exponent, quotient*8 + remainder
    logic signed [Q-1:0] quotient;   // floor(exponent/8), in [-8,7]
    logic        [R-1:0] remainder;  // exponent mod 8, in [0,7]
  } lns_t;

  localparam int unsigned LNS_W = 16;

  // Exact-zero element constructor (matches LNS::make_zero()).
  function automatic lns_t lns_zero();
    lns_t z;
    z.sign = 1'b0; z.zero = 1'b1; z.exponent = '0; z.quotient = '0; z.remainder = '0;
    return z;
  endfunction

  // Mitchell 2^(r/8) LUT, values * 256 (9-bit), indexed by remainder r.
  // shift_8bit_log2_LUT_base8[] in add_unit.cpp.
  function automatic logic [8:0] mitchell_lut(input int unsigned idx);
    case (idx)
      0: return 9'd256; 1: return 9'd279; 2: return 9'd304; 3: return 9'd332;
      4: return 9'd362; 5: return 9'd394; 6: return 9'd431; 7: return 9'd470;
      default: return 9'd256;
    endcase
  endfunction

  // Map a full signed exponent into [EXP_MIN, EXP_MAX]: underflow flushes to
  // zero, overflow saturates to the largest magnitude (LNS::from_exponent).
  // For the in-range case exponent[6:0] already carries floored q,r as bit
  // slices (two's-complement >>3 == arithmetic slice), so no divider is needed.
  function automatic lns_t from_exponent_f(input logic sgn, input logic signed [11:0] e);
    lns_t r;
    logic signed [B-1:0] exp7;
    if (e < EXP_MIN) return lns_zero();
    if (e > EXP_MAX) begin
      r.sign = sgn; r.zero = 1'b0;
      r.exponent = 7'sd63; r.quotient = 4'sd7; r.remainder = 3'd7;
      return r;
    end
    exp7 = e[B-1:0];
    r.sign = sgn; r.zero = 1'b0;
    r.exponent  = exp7;
    r.quotient  = exp7[B-1:3];   // floor(e/8)
    r.remainder = exp7[2:0];     // e mod 8, non-negative
    return r;
  endfunction

  // LNS multiply: sign XOR, exponent add, zero-propagate, saturate.
  function automatic lns_t lns_mul_f(input lns_t a, input lns_t b);
    logic sgn;
    logic signed [8:0] esum;   // [-64,63] + [-64,63] -> [-128,126]
    if (a.zero || b.zero) return lns_zero();
    sgn  = a.sign ^ b.sign;
    esum = $signed(a.exponent) + $signed(b.exponent);
    return from_exponent_f(sgn, $signed({{3{esum[8]}}, esum}));
  endfunction

  // --- N-way log-domain adder, split into the four C stages ------------------
  // Inputs / intermediates are carried as flat packed vectors so the functions
  // stay portable across simulators; see add_unit.cpp for the reference.

  // sort_shift_accumulate, split into two pipeline-friendly halves:
  //   decode_inputs      : per product -> (target bucket idx, addend = 2^shift)
  //   accumulate_buckets : sum the 8 addends into their 16 buckets
  // build_buckets composes them so the combinational reference (lns_add8) and
  // the pipelined datapath (lns_mac8, which registers between the two halves)
  // stay bit-identical. A zeroed input decodes to addend 0, so it adds nothing.
  // Layout per input i in the 24-bit slot: [23:20]=idx, [19:0]=addend.
  function automatic logic [NLEN*24-1:0] decode_inputs(input logic [NLEN*16-1:0] prods);
    lns_t              e;
    logic [3:0]        idx;
    logic [3:0]        shft;
    logic signed [5:0] qext;
    logic [19:0]       addend;
    for (int i = 0; i < NLEN; i++) begin
      e      = lns_t'(prods[i*16 +: 16]);
      idx    = {e.sign, e.remainder};            // sign ? 8+r : r
      qext   = $signed(e.quotient) + 6'sd8;      // quotient + QBIAS, in [0,15]
      shft   = qext[3:0];
      addend = e.zero ? 20'd0 : (20'd1 << shft);
      decode_inputs[i*24 +: 20]      = addend;
      decode_inputs[i*24 + 20 +: 4]  = idx;
    end
  endfunction

  // Scatter-add as a parallel tree, NOT a sequential array read-modify-write:
  // an RMW loop with a data-dependent index serializes into an 8-deep adder
  // chain (~38 logic levels — it will not close 10 ns). accumulate_group sums
  // one 4-input half into the 16 buckets (each bucket = a masked 4-term tree);
  // combine_buckets adds the two halves. lns_mac8 registers between the two, so
  // no bucket sees more than a 4-term tree of adds in a cycle.
  function automatic logic [M*20-1:0] accumulate_group(input logic [NLEN*24-1:0] dec,
                                                       input int unsigned base);
    logic [19:0] m [0:3];
    logic [3:0]  idx;
    logic [19:0] addend;
    for (int b = 0; b < M; b++) begin
      for (int g = 0; g < 4; g++) begin
        idx    = dec[(base+g)*24 + 20 +: 4];
        addend = dec[(base+g)*24 +: 20];
        m[g]   = (idx == b[3:0]) ? addend : 20'd0;
      end
      accumulate_group[b*20 +: 20] = (m[0] + m[1]) + (m[2] + m[3]);
    end
  endfunction

  function automatic logic [M*20-1:0] combine_buckets(input logic [M*20-1:0] lo,
                                                      input logic [M*20-1:0] hi);
    for (int b = 0; b < M; b++)
      combine_buckets[b*20 +: 20] = lo[b*20 +: 20] + hi[b*20 +: 20];
  endfunction

  function automatic logic [M*20-1:0] accumulate_buckets(input logic [NLEN*24-1:0] dec);
    return combine_buckets(accumulate_group(dec, 0), accumulate_group(dec, 4));
  endfunction

  function automatic logic [M*20-1:0] build_buckets(input logic [NLEN*16-1:0] prods);
    return accumulate_buckets(decode_inputs(prods));
  endfunction

  // scale_back_mitchell_shift8: multiply each bucket by its Mitchell constant
  // (constant multiply -> LUT fabric, no DSP). 16 x 32-bit -> 512-bit.
  function automatic logic [M*32-1:0] scale_buckets(input logic [M*20-1:0] buckets);
    logic [19:0] ps;
    for (int i = 0; i < M; i++) begin
      ps = buckets[i*20 +: 20];
      scale_buckets[i*32 +: 32] = 32'(ps * mitchell_lut(i % 8));
    end
  endfunction

  // addition_unit: positive buckets (sign 0) minus negative buckets (sign 1).
  // Balanced trees (not accumulate-in-a-loop), split across a register: the
  // pos/neg 8-way sums (reduce_partials) then the final subtract (reduce_final).
  // Carry between them (72b): [71:36]=pos sum, [35:0]=neg sum.
  function automatic logic [71:0] reduce_partials(input logic [M*32-1:0] scaled);
    logic [35:0] p [0:7];
    logic [35:0] n [0:7];
    logic [35:0] pos, neg;
    for (int i = 0; i < 8; i++) begin
      p[i] = {4'd0, scaled[i*32 +: 32]};
      n[i] = {4'd0, scaled[(i+8)*32 +: 32]};
    end
    pos = ((p[0] + p[1]) + (p[2] + p[3])) + ((p[4] + p[5]) + (p[6] + p[7]));
    neg = ((n[0] + n[1]) + (n[2] + n[3])) + ((n[4] + n[5]) + (n[6] + n[7]));
    return {pos, neg};
  endfunction

  function automatic logic signed [35:0] reduce_final(input logic [71:0] carry);
    return $signed(carry[71:36]) - $signed(carry[35:0]);
  endfunction

  function automatic logic signed [35:0] reduce_buckets(input logic [M*32-1:0] scaled);
    return reduce_final(reduce_partials(scaled));
  endfunction

  // index_of_closest_value: nearest Mitchell LUT entry to a 9-bit mantissa,
  // first-minimum wins on ties. The C loop searches 8 abs-diffs sequentially,
  // which synthesizes to a deep dependent adder chain. Because the LUT is sorted
  // ascending, the identical answer is a set of fixed thresholds: the switch
  // from index i to i+1 sits at floor((LUT[i]+LUT[i+1])/2), with an exact-tie
  // value resolving to the smaller index (matching the strict-< update). The
  // seven constants below are those midpoints; each one is checked in the cocotb
  // suite by the end-to-end golden compare.
  function automatic logic [2:0] closest_index(input logic [8:0] val);
    if (val <= 9'd267) return 3'd0;   // (256+279)/2
    if (val <= 9'd291) return 3'd1;   // (279+304)/2
    if (val <= 9'd318) return 3'd2;   // (304+332)/2, tie -> 2
    if (val <= 9'd347) return 3'd3;   // (332+362)/2, tie -> 3
    if (val <= 9'd378) return 3'd4;   // (362+394)/2, tie -> 4
    if (val <= 9'd412) return 3'd5;   // (394+431)/2
    if (val <= 9'd450) return 3'd6;   // (431+470)/2
    return 3'd7;
  endfunction

  // convertback: fixed-point accumulator (true sum * 2^16) back to an LNS
  // element. Priority-encode the leading one, take the 9-bit mantissa below it,
  // and map to (quotient, remainder). A mantissa past the LUT[7]=470 / 512
  // midpoint rolls up to the next octave (r=0, q+1) — copied verbatim.
  //
  // Split into three pipeline-friendly stages, each a shallow combinational
  // block so the convert-back (the second long pole) closes 10 ns:
  //   convert_lead : zero test, absolute value, leading-one priority encode
  //   convert_mant : barrel-shift the 9-bit mantissa out from under the lead 1
  //   convert_final: Mitchell classify + octave roll-up + saturate
  // Carry between lead->mant (44b): [43]zero [42]sign [41:36]lop [35:0]|sum|
  // Carry between mant->final (17b): [16]zero [15]sign [14:9]lop [8:0]mantissa
  function automatic logic [43:0] convert_lead(input logic signed [35:0] s);
    logic        sgn;
    logic [35:0] absv;
    logic [5:0]  lop;
    if (s == 36'sd0) return {1'b1, 43'd0};               // zero flag set
    sgn  = s[35];
    absv = sgn ? (-s) : s;
    lop  = 6'd0;
    for (int i = 0; i < 36; i++) if (absv[i]) lop = 6'(i);  // position of leading 1
    return {1'b0, sgn, lop, absv};
  endfunction

  function automatic logic [16:0] convert_mant(input logic [43:0] carry);
    logic        sgn;
    logic [35:0] absv;
    logic [5:0]  lop;
    logic [8:0]  mant;
    if (carry[43]) return {1'b1, 16'd0};
    sgn  = carry[42];
    lop  = carry[41:36];
    absv = carry[35:0];
    mant = (lop >= 8) ? 9'(absv >> (lop - 8)) : 9'(absv << (8 - lop));
    return {1'b0, sgn, lop, mant};
  endfunction

  function automatic lns_t convert_final(input logic [16:0] carry);
    logic               sgn;
    logic [5:0]         lop;
    logic [8:0]         mant;
    logic signed [11:0] q, e;
    logic [2:0]         rem;
    if (carry[16]) return lns_zero();
    sgn  = carry[15];
    lop  = carry[14:9];
    mant = carry[8:0];
    q    = $signed({6'd0, lop}) - (QBIAS + 8);           // undo 2^16 acc scale
    if (mant > 9'd491) begin                             // (470 + 512) / 2
      q   = q + 12'sd1;
      rem = 3'd0;
    end else begin
      rem = closest_index(mant);
    end
    e = q * 8 + $signed({9'd0, rem});
    return from_exponent_f(sgn, e);
  endfunction

  function automatic lns_t convertback_f(input logic signed [35:0] s);
    return convert_final(convert_mant(convert_lead(s)));
  endfunction

endpackage
