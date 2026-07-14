#ifndef ADD_UNIT_H
#define ADD_UNIT_H

#include "LNS_datatype.h" // Ensure this header file includes LNS class definition

extern "C" {

    int index_of_closest_value(int input_value, const int LUT[Gamma]);

    // Sorting Unit: shift each input by its biased quotient and accumulate
    // into the (sign x remainder) partial-sum bucket
    void sort_shift_accumulate(LNS<B, Q, R, Gamma> input[N], sum_t partial_sum[M]);

    // Scale Back: apply the Mitchell 2^(r/8) LUT (values stored shifted left by 8 bits)
    void scale_back_mitchell_shift8(sum_t partial_sum[M], mul_t partial_sum_scale[M]);

    // Addition Unit: positive buckets minus negative buckets
    void addition_unit(mul_t partial_sum_scale[M], add_unit_t &final_sum);

    // Conversion: fixed-point accumulator value back to LNS format
    void convertback(add_unit_t &sum, LNS<B, Q, R, Gamma> &final_sum);

    // Main adder function
    void adder(LNS<B, Q, R, Gamma> inputs[N], LNS<B, Q, R, Gamma> &final_sum);
}

#endif
