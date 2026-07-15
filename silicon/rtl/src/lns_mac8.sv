// Pipelined LNS dot product of two 8-element vectors: 8 multiplies + the
// 8-way log adder, one result per clock (II=1).
//
// Datapath == lns_add8 fed by 8 lns_mul, but cut into register stages so the
// long bucket/scale/reduce/convert chain closes timing at 100 MHz. Every stage
// calls the same lns_pkg functions as the combinational reference, so the
// pipeline is bit-exact against it. A valid bit and a caller tag ride alongside
// the data so the top can place each result without tracking latency by hand.
//
// Ten stages (LAT): multiply / decode / accumulate-halves / combine / scale /
// reduce-partials / reduce-final / leading-one / mantissa / finalize. The extra
// splits exist purely for timing — the scatter-add bucket build, the signed
// reduction, and the convert-back were the long combinational poles.
// Throughput = 1 dot product / cycle.
//
// use_dsp="no": the only multiplies are the 16 Mitchell constant scales; the
// whole premise of LNS is a DSP-free MAC, so they are forced to LUT fabric
// (the HLS reference did the same with BIND_OP impl=fabric). Without this,
// Vivado maps those constant multiplies to 14 DSP48s.

(* use_dsp = "no" *)
module lns_mac8
  import lns_pkg::*;
#(
  parameter int unsigned TAG_W = 6
) (
  input  logic                 clk,
  input  logic                 rst_n,
  input  logic                 valid_in,
  input  logic [TAG_W-1:0]     tag_in,
  input  logic [NLEN*16-1:0]   a_vec,   // 8 A elements, a_vec[k*16 +: 16]
  input  logic [NLEN*16-1:0]   b_vec,   // 8 B elements, b_vec[k*16 +: 16]
  output logic                 valid_out,
  output logic [TAG_W-1:0]     tag_out,
  output logic [15:0]          result
);

  localparam int unsigned LAT = 10;

  // Stage 1: 8 parallel multiplies (combinational into the stage-1 registers).
  logic [NLEN*16-1:0] prod_c;
  always_comb
    for (int k = 0; k < NLEN; k++)
      prod_c[k*16 +: 16] = lns_mul_f(lns_t'(a_vec[k*16 +: 16]),
                                     lns_t'(b_vec[k*16 +: 16]));

  logic [NLEN*16-1:0] prod_q;   // s1: products
  logic [NLEN*24-1:0] dec_q;    // s2: per-input (bucket, addend)
  logic [M*20-1:0]    blo_q;    // s3: bucket sums, inputs 0..3
  logic [M*20-1:0]    bhi_q;    // s3: bucket sums, inputs 4..7
  logic [M*20-1:0]    buck_q;   // s4: 16 combined bucket sums
  logic [M*32-1:0]    scal_q;   // s5: Mitchell-scaled buckets
  logic [71:0]        part_q;   // s6: pos/neg partial sums
  logic signed [35:0] acc_q;    // s7: signed reduction
  logic [43:0]        lead_q;   // s8: sign / leading-one / |sum|
  logic [16:0]        mant_q;   // s9: sign / leading-one / mantissa
  logic [15:0]        res_q;    // s10: LNS result

  logic [LAT-1:0]   vld_sr;
  logic [TAG_W-1:0] tag_sr [0:LAT-1];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      prod_q <= '0; dec_q <= '0; blo_q <= '0; bhi_q <= '0; buck_q <= '0;
      scal_q <= '0; part_q <= '0; acc_q <= '0; lead_q <= '0; mant_q <= '0; res_q <= '0;
      vld_sr <= '0;
      for (int i = 0; i < LAT; i++) tag_sr[i] <= '0;
    end else begin
      prod_q <= prod_c;                         // s1: multiplies latched
      dec_q  <= decode_inputs(prod_q);          // s2: decode to buckets/addends
      blo_q  <= accumulate_group(dec_q, 0);     // s3: partial buckets, inputs 0..3
      bhi_q  <= accumulate_group(dec_q, 4);     // s3: partial buckets, inputs 4..7
      buck_q <= combine_buckets(blo_q, bhi_q);  // s4: combine partials
      scal_q <= scale_buckets(buck_q);          // s5: Mitchell scale
      part_q <= reduce_partials(scal_q);        // s6: pos/neg 8-way sums
      acc_q  <= reduce_final(part_q);           // s7: pos - neg
      lead_q <= convert_lead(acc_q);            // s8: priority encode + abs
      mant_q <= convert_mant(lead_q);           // s9: extract mantissa
      res_q  <= convert_final(mant_q);          // s10: back to LNS

      vld_sr    <= {vld_sr[LAT-2:0], valid_in};
      tag_sr[0] <= tag_in;
      for (int i = 1; i < LAT; i++) tag_sr[i] <= tag_sr[i-1];
    end
  end

  assign valid_out = vld_sr[LAT-1];
  assign tag_out   = tag_sr[LAT-1];
  assign result    = res_q;

endmodule
