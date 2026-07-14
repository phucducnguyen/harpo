
#include "mul_unit.h"

// LNS multiplication: sign = s1 XOR s2, exponent = e1 + e2 (saturated).
// Zero propagation and exponent saturation live in LNS::operator*.
void multiply(const LNS<B, Q, R, Gamma>& a, const LNS<B, Q, R, Gamma>& b, LNS<B, Q, R, Gamma>& result) {
    result = a * b;
}

// Implement multiplication of LNS numbers
void multiply_array(const LNS<B, Q, R, Gamma> array_input_a[N], const LNS<B, Q, R, Gamma> array_input_b[N], LNS<B, Q, R, Gamma> result[N]) {
// #pragma HLS PIPELINE II=1 // do not put, increase latency and FF and LUT

    for (int i=0; i<N; i++){
        result[i] = array_input_a[i] * array_input_b[i];
    }
}
