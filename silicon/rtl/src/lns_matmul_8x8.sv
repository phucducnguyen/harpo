// Top: 8x8 LNS matrix multiply, R = A * B.
//
// Interface (simple synchronous, no AXI):
//   clk, rst_n              standard, active-low async reset
//   start                   1-cycle pulse: latch a_flat/b_flat and begin
//   a_flat [1023:0]         A row-major; element A[i][k] at a_flat[(i*8+k)*16 +: 16]
//   b_flat [1023:0]         B row-major; element B[k][j] at b_flat[(k*8+j)*16 +: 16]
//   r_flat [1023:0]         R row-major; element R[i][j] at r_flat[(i*8+j)*16 +: 16]
//   done                    high once all 64 outputs are valid; held until next start
//
// Each 16-bit lane is one packed lns_pkg::lns_t. One pipelined lns_mac8 is
// time-shared: the 64 output positions are streamed through it one per clock
// (an internal counter picks row i / column j), results land by their tag.
// This is the whole point of the hand-RTL comparison — the HLS kernel pays
// II=16 per output for m_axi port serialization; here the operands are already
// on-chip in registers, so issue is II=1 and a full matmul is
// 1 (latch) + 64 (issue) + LAT (drain) cycles. No memory ports, no AXI.

module lns_matmul_8x8
  import lns_pkg::*;
(
  input  logic          clk,
  input  logic          rst_n,
  input  logic          start,
  input  logic [1023:0] a_flat,
  input  logic [1023:0] b_flat,
  output logic          done,
  output logic [1023:0] r_flat
);

  localparam int unsigned TAG_W = 6;   // 0..63

  logic [1023:0] a_reg, b_reg;
  logic [1023:0] r_reg;
  logic          busy;
  logic [6:0]    issue_cnt;    // 0..64
  logic [6:0]    result_cnt;   // 0..64

  // Operand select for the position currently being issued.
  logic [2:0]         i_sel, j_sel;
  logic [NLEN*16-1:0] a_row, b_col;
  assign i_sel = issue_cnt[5:3];
  assign j_sel = issue_cnt[2:0];
  always_comb begin
    for (int k = 0; k < NLEN; k++) begin
      a_row[k*16 +: 16] = a_reg[({i_sel, k[2:0]}) * 16 +: 16];   // A[i][k]
      b_col[k*16 +: 16] = b_reg[({k[2:0], j_sel}) * 16 +: 16];   // B[k][j]
    end
  end

  logic            issuing;
  logic            v_out;
  logic [TAG_W-1:0] tag_out;
  logic [15:0]     mac_result;
  assign issuing = busy && (issue_cnt < 7'd64);

  lns_mac8 #(.TAG_W(TAG_W)) u_mac (
    .clk       (clk),
    .rst_n     (rst_n),
    .valid_in  (issuing),
    .tag_in    (issue_cnt[TAG_W-1:0]),
    .a_vec     (a_row),
    .b_vec     (b_col),
    .valid_out (v_out),
    .tag_out   (tag_out),
    .result    (mac_result)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      busy <= 1'b0; done <= 1'b0;
      issue_cnt <= '0; result_cnt <= '0;
      a_reg <= '0; b_reg <= '0; r_reg <= '0;
    end else begin
      if (start && !busy) begin
        a_reg      <= a_flat;
        b_reg      <= b_flat;
        busy       <= 1'b1;
        done       <= 1'b0;
        issue_cnt  <= '0;
        result_cnt <= '0;
      end else if (busy) begin
        if (issue_cnt < 7'd64) issue_cnt <= issue_cnt + 7'd1;
        if (v_out) begin
          r_reg[tag_out * 16 +: 16] <= mac_result;
          result_cnt <= result_cnt + 7'd1;
          if (result_cnt == 7'd63) begin
            busy <= 1'b0;
            done <= 1'b1;
          end
        end
      end
    end
  end

  assign r_flat = r_reg;

endmodule
