#ifndef LNS_DATATYPE_H
#define LNS_DATATYPE_H

#include <ap_int.h>
#include <cstdint>
#include <cmath>
#include <cstdio>

// Define base factor Gamma, bit-width B, and bit-widths for quotient and remainder
constexpr uint8_t B = 7;
constexpr uint8_t Q = 4;  // Bit-width for quotient
constexpr uint8_t R = 3;  // Bit-width for remainder
constexpr uint8_t Gamma = 8; // Base 8 - if Gamma = 4 => base 4

constexpr uint8_t M = Gamma*2; // Number of partial-sum buckets - Log8 => 8 positive + 8 negative
constexpr uint8_t N = 8; // Number of accumulators

// The quotient is SIGNED: q in [-8, 7], so magnitudes from 2^-8 up to 2^7.875
// are representable (an unsigned quotient cannot encode values < 1.0, which is
// fatal for DNN weights). Accumulation hardware shifts by the biased quotient
// q + QBIAS in [0, 15], and convertback compensates the bias.
constexpr int8_t QBIAS = 8;
constexpr int8_t EXP_MIN = -(QBIAS * Gamma);          // -64: encodes 2^-8
constexpr int8_t EXP_MAX = (QBIAS - 1) * Gamma + (Gamma - 1); // 63: encodes 2^7.875

// Typedefs for clarity and maintainability
typedef ap_uint<1> sign_t;
typedef ap_int<B> exponent_t;   // signed total exponent = q*Gamma + r, in [-64, 63]
typedef ap_int<Q> quotient_t;   // signed quotient, in [-8, 7]
typedef ap_uint<R> remainder_t; // remainder in [0, 7] (floored division, always non-negative)

// Accumulator widths (see add_unit.cpp):
//  - per-bucket sum of N shifted contributions: N * 2^(Q_max+QBIAS) = 8 * 2^15 = 2^18 -> 20 bits
//  - after Mitchell LUT scale (x <= 470 < 2^9): < 2^29 -> 32 bits
//  - signed grand total across 8 buckets each sign: < 2^32 -> 36-bit signed
typedef ap_uint<20> sum_t;
typedef ap_uint<32> mul_t;
typedef ap_int<36> add_unit_t;

// Define the LNS data type using a struct
template<uint8_t B, uint8_t Q, uint8_t R, uint8_t Gamma>
struct LNS {
    // Data members
    sign_t sign;           // Sign bit (1-bit)
    ap_uint<1> zero;       // Exact-zero flag (zero is not representable as 2^e)
    exponent_t exponent;   // Full signed exponent
    quotient_t quotient;   // Quotient part of the exponent (signed)
    remainder_t remainder; // Remainder part of the exponent (non-negative)

    // Default constructor: exact zero
    LNS() : sign(0), zero(1), exponent(0), quotient(0), remainder(0) {}

    // Constructor from a full signed exponent (floored division keeps r >= 0)
    LNS(sign_t s, exponent_t exp) : sign(s), zero(0), exponent(exp) {
        int e = exp.to_int();
        int q = (e >= 0) ? e / Gamma : -(((-e) + Gamma - 1) / Gamma); // floor(e/Gamma)
        quotient = quotient_t(q);
        remainder = remainder_t(e - q * Gamma);
    }

    LNS(sign_t s, quotient_t q, remainder_t r) : sign(s), zero(0), quotient(q), remainder(r) {
        exponent = exponent_t(q.to_int() * Gamma + r.to_int());
    }

    static LNS make_zero() { return LNS(); }

    // Map a full exponent into the representable range [EXP_MIN, EXP_MAX]:
    // overflow saturates to the largest magnitude, underflow flushes to zero.
    static LNS from_exponent(sign_t s, int e) {
        if (e < EXP_MIN) return make_zero();
        if (e > EXP_MAX) return LNS(s, exponent_t(EXP_MAX));
        return LNS(s, exponent_t(e));
    }

    // Conversion from a floating-point number to LNS format.
    // Host/testbench conversion helper — not part of the synthesized MAC datapath.
    static LNS from_float(float value) {
        if (value == 0.0f) {
            return make_zero();
        }
        sign_t s = value < 0 ? 1 : 0;
        float e = std::log2(std::fabs(value));
        // Round the scaled exponent as a whole so the remainder carry
        // propagates into the quotient instead of wrapping mod 8.
        long E = std::lround(double(Gamma) * e);
        return from_exponent(s, int(E));
    }

    // Convert LNS to a float (for simulation purposes)
    float to_float() const {
        if (zero) return 0.0f;
        float value = std::pow(2.0f, float(exponent.to_int()) / Gamma);
        return sign.to_int() ? -value : value;
    }

    // Arithmetic operations
    LNS operator*(const LNS& other) const {
        if (zero || other.zero) return make_zero();
        sign_t result_sign = sign ^ other.sign;  // XOR to determine the sign
        int e = exponent.to_int() + other.exponent.to_int();
        return from_exponent(result_sign, e);
    }

    // Print function to display LNS representation
    void print() const {
        if (zero) {
            printf("LNS Representation: zero\n");
            return;
        }
        printf("LNS Representation: ");
        printf("Sign: %d, ", sign.to_int());
        printf("Exponent: (Quotient: %d, Remainder: %d), ", quotient.to_int(), remainder.to_int());
        printf("Full Exponent: %d\n", exponent.to_int());
    }
};



// Helper structure to create 2D array support for LNS
template<uint8_t Rows, uint8_t Cols, uint8_t B, uint8_t Q, uint8_t R, uint8_t Gamma>
struct LNS2DArray {
    LNS<B, Q, R, Gamma> data[Rows][Cols];  // 2D array of LNS

    LNS<B, Q, R, Gamma>* operator[](int row) {
        return data[row];
    }

    const LNS<B, Q, R, Gamma>* operator[](int row) const {
        return data[row];
    }

    void print() {
        for (int i = 0; i < Rows; i++) {
            for (int j = 0; j < Cols; j++) {
                data[i][j].print();
            }
        }
    }
};


#endif // LNS_DATATYPE_H
