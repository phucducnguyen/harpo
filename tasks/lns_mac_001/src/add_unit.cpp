#include "add_unit.h"

// Mitchell 2^(r/8) LUT, values stored shifted left by 8 bits (2^(r/8) * 256).
// float mitchell_LUT_base8[8]={0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875};
// float log2_LUT_base8[8]={1, 1.09051, 1.18921, 1.29684, 1.41421, 1.54221, 1.68179, 1.83401};
const int shift_8bit_log2_LUT_base8[8]={256, 279, 304, 332, 362, 394, 431, 470}; // need 9 bits to store

// The accumulator carries the true sum scaled by 2^16:
//   2^QBIAS (=2^8) from the biased quotient shift in sort_shift_accumulate,
//   2^8 from the shifted Mitchell LUT in scale_back_mitchell_shift8.
constexpr int ACC_SCALE_BITS = QBIAS + 8;

// Compare the input with the values inside a LUT to find the position of the closest value
int index_of_closest_value(int input_value, const int LUT[Gamma]) {
    #pragma HLS ARRAY_PARTITION variable=LUT complete dim=1 // Partition the LUT for parallel access

    int closest_index = 0;
    int min_diff = abs(input_value - LUT[0]);

    // Iterate through the LUT array to find the closest value
    for (int i = 0; i < Gamma; i++) {
        int diff = abs(input_value - LUT[i]);
        if (diff < min_diff) {
            min_diff = diff;
            closest_index = i;
        }
    }
    return closest_index; // Return the index of the closest LUT value
}

// Sorting Unit: shift each input by its biased quotient and accumulate it into
// the (sign x remainder) bucket. The quotient is signed in [-8, 7], so the
// shift amount q + QBIAS is in [0, 15] and every contribution fits in sum_t.
void sort_shift_accumulate(LNS<B, Q, R, Gamma> input[N], sum_t partial_sum[M]){
    #pragma HLS ARRAY_PARTITION variable=partial_sum complete dim=1 // Enables parallel access to partial_sum
    for (int i=0; i<N; i++){
        if (input[i].zero) continue; // exact zeros contribute nothing
        // Positive: index from 0 to 7  -  Negative: index from 8 to 15
        ap_uint<4> sign_offset = input[i].sign ? Gamma : 0;
        ap_uint<6> index = input[i].remainder + sign_offset;
        ap_uint<4> shift = ap_uint<4>(input[i].quotient.to_int() + QBIAS);
        partial_sum[index] += (sum_t(1) << shift);
    }
}

// Scale the partial sums
// Using LUT to store shift-by-8 Mitchell approx - to reduce the use of DSP
void scale_back_mitchell_shift8(sum_t partial_sum[M], mul_t partial_sum_scale[M]){
    #pragma HLS ARRAY_PARTITION variable=partial_sum complete dim=1
    #pragma HLS ARRAY_PARTITION variable=partial_sum_scale complete dim=1
    #pragma HLS ARRAY_PARTITION variable=shift_8bit_log2_LUT_base8 complete dim=1

    for (int i = 0; i < M; i++) {
        #pragma HLS BIND_OP variable=partial_sum_scale op=mul impl=fabric latency=-1
        // Scaling back with a predefined lookup table for the shift values
        partial_sum_scale[i] = partial_sum[i] * shift_8bit_log2_LUT_base8[i % 8];
    }
}

// Add all scaled values - Big Sum
void addition_unit(mul_t partial_sum_scale[M], add_unit_t &final_sum) {
    #pragma HLS ARRAY_PARTITION variable=partial_sum_scale complete dim=1 // Enables parallel access to array

    add_unit_t positive_sum = 0;
    add_unit_t negative_sum = 0;

    // Process positive and negative sums in parallel
    for (int i = 0; i < (M >> 1); i++) {
        #pragma HLS UNROLL // Unroll for increased performance
        positive_sum += partial_sum_scale[i];
        negative_sum -= partial_sum_scale[i + (M >> 1)];
    }

    final_sum = positive_sum + negative_sum;
}

// Convert the fixed-point accumulator value (true sum x 2^16) back to LNS
void convertback(add_unit_t &sum, LNS<B, Q, R, Gamma> &final_sum){
    #pragma HLS PIPELINE II=1 // must have

    // Handle zero case
    if (sum == 0) {
        final_sum = LNS<B, Q, R, Gamma>::make_zero();
        return;
    }
    // Extract sign and integer magnitude (no float ops in the datapath)
    sign_t s = sum < 0 ? 1 : 0;
    ap_uint<add_unit_t::width> abs_value = s ? ap_uint<add_unit_t::width>(-sum) : ap_uint<add_unit_t::width>(sum);

    // Find the leading one position (portable priority encoder)
    int leading_one_pos = 0;
    for (int i = 0; i < add_unit_t::width; i++) {
        #pragma HLS UNROLL
        if (abs_value[i]) leading_one_pos = i;
    }

    // Quotient of the true sum: undo the 2^16 accumulator scale
    int q = leading_one_pos - ACC_SCALE_BITS;

    // Take the 9 bits below (and including) the leading one -> mantissa in [256, 511]
    int mantissa = (leading_one_pos >= 8)
        ? int(abs_value >> (leading_one_pos - 8))
        : int(abs_value << (8 - leading_one_pos));

    // remainder = position of the closest Mitchell LUT value; a mantissa past the
    // midpoint of LUT[7]=470 and 512 is closer to the next octave (r=0, q+1)
    int r;
    if (mantissa > (shift_8bit_log2_LUT_base8[7] + 512) / 2) {
        q += 1;
        r = 0;
    } else {
        r = index_of_closest_value(mantissa, shift_8bit_log2_LUT_base8);
    }

    // Underflow flushes to zero, overflow saturates (handled by from_exponent)
    final_sum = LNS<B, Q, R, Gamma>::from_exponent(s, q * Gamma + r);
}



// Top-level adder function
void adder(LNS<B, Q, R, Gamma> inputs[N], LNS<B, Q, R, Gamma> &final_sum) {
    sum_t partial_sum[M];
    #pragma HLS ARRAY_PARTITION variable=partial_sum complete
    // ap_uint's default constructor does NOT zero-initialize (and `={0}` only
    // touches element 0) — every bucket must be cleared explicitly
    for (int i = 0; i < M; i++) {
        #pragma HLS UNROLL
        partial_sum[i] = 0;
    }
    mul_t partial_sum_results[M];
    add_unit_t final_sum_int=0;

    sort_shift_accumulate(inputs, partial_sum);
    scale_back_mitchell_shift8(partial_sum, partial_sum_results);

    addition_unit(partial_sum_results, final_sum_int);

    // Convert final sum to LNS format
    convertback(final_sum_int, final_sum);
}
