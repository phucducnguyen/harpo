// Silicon-workspace variant of the HARPO-fixed winner
// (docs/case-study/lns_mac_001_ollama_run1_winner.mac.cpp).
//
// ONE deliberate deviation, control protocol only:
//   ap_ctrl_none  ->  s_axilite (block-level start/done over AXI-Lite)
// Reasons: (1) cosim cannot drive an ap_ctrl_none top unless it is fully
// pipelined at II=1 (COSIM 212-345); (2) the PYNQ-Z2 overlay needs AXI-Lite
// control + buffer offsets to launch the kernel from Python anyway.
// The datapath, loop structure, and the case-study pragma fix
// (inner-loop PIPELINE II=1) are byte-identical to the winner. The unused
// legacy function mac_nxn (dead code, never called by the top) is dropped.

#include "mac.h"

void mac_array(LNS<B, Q, R, Gamma> array_input_a[N], LNS<B, Q, R, Gamma> array_input_b[N], LNS<B, Q, R, Gamma> &result){
    LNS<B, Q, R, Gamma> multiplier_result[N];

    multiply_array(array_input_a, array_input_b, multiplier_result);
    adder(multiplier_result, result);
}

void mac_nxn_array(LNS<B, Q, R, Gamma> array_input_a[N][N], LNS<B, Q, R, Gamma> array_input_b[N][N], LNS<B, Q, R, Gamma> result[N][N]){
#pragma HLS INTERFACE m_axi port=array_input_a offset=slave bundle=gmem
#pragma HLS INTERFACE m_axi port=array_input_b offset=slave bundle=gmem
#pragma HLS INTERFACE m_axi port=result offset=slave bundle=gmem
#pragma HLS INTERFACE s_axilite port=return
    // Extract the i-th row from input_a and the j-th column from input_b
    LNS<B, Q, R, Gamma> row_a[N];
    LNS<B, Q, R, Gamma> col_b[N];
    LNS<B, Q, R, Gamma> temp_result;

    // Perform matrix multiplication using the mac function
    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            #pragma HLS PIPELINE II=1
            for (int k = 0; k < N; k++) {
                row_a[k] = array_input_a[i][k];
                col_b[k] = array_input_b[k][j];
            }
            mac_array(row_a,col_b,temp_result);
            result[i][j] = temp_result;
        }
    }
}
