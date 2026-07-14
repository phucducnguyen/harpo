// Golden-model testbench for the LNS MAC.
//
// Every check compares the DUT against a double-precision reference computed
// from the QUANTIZED inputs (LNS grid values), so it measures datapath error
// only — input quantization error is excluded by construction.
//
// Error budget for a passing MAC:
//   - Mitchell LUT entries rounded to 9 bits:      <= ~0.2% per bucket
//   - convertback rounding to the 2^(1/8) grid:    <= ~4.4% of the result
//   - underflow flush-to-zero below 2^-8
// Tolerance: |dut - golden| <= 5% |golden| + 1% sum|products| + 2^-8.

#include "mac.h"
#include <cassert>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <random>

typedef LNS<B, Q, R, Gamma> lns_t;

static int failures = 0;

// Largest representable magnitude: 2^(EXP_MAX/8) = 2^7.875. A true sum beyond
// this saturates in the DUT by design, so the golden model clamps to match.
static const double MAX_REPR = std::pow(2.0, double(EXP_MAX) / Gamma);

static double clamp_repr(double v) {
    if (v > MAX_REPR) return MAX_REPR;
    if (v < -MAX_REPR) return -MAX_REPR;
    return v;
}

static double tolerance(double golden, double sum_abs) {
    return 0.05 * std::fabs(golden) + 0.01 * sum_abs + 1.0 / 256.0;
}

// Run one MAC through the DUT and check it against the double-precision golden
static void check_mac(const float a[N], const float b[N], const char* label) {
    lns_t a_lns[N], b_lns[N], result;
    double golden = 0.0, sum_abs = 0.0;

    for (int i = 0; i < N; i++) {
        a_lns[i] = lns_t::from_float(a[i]);
        b_lns[i] = lns_t::from_float(b[i]);
        // golden uses the quantized (grid) values, in double precision
        double p = double(a_lns[i].to_float()) * double(b_lns[i].to_float());
        golden += p;
        sum_abs += std::fabs(p);
    }

    mac_array(a_lns, b_lns, result);
    golden = clamp_repr(golden);
    double dut = result.to_float();
    double err = std::fabs(dut - golden);
    double tol = tolerance(golden, sum_abs);

    if (err > tol) {
        failures++;
        std::cout << "FAIL [" << label << "] dut=" << dut << " golden=" << golden
                  << " err=" << err << " tol=" << tol << std::endl;
    }
}

static void directed_tests() {
    { // All zeros in -> exact zero out (zero must not encode as +1.0)
        float a[N] = {0}, b[N] = {0};
        lns_t a_lns[N], b_lns[N], result;
        for (int i = 0; i < N; i++) { a_lns[i] = lns_t::from_float(a[i]); b_lns[i] = lns_t::from_float(b[i]); }
        mac_array(a_lns, b_lns, result);
        if (!result.zero || result.to_float() != 0.0f) {
            failures++;
            std::cout << "FAIL [all-zero] expected exact zero, got " << result.to_float() << std::endl;
        }
    }
    { // Values below 1.0 (unrepresentable with the old unsigned exponent)
        float a[N] = {0.5f, 0.25f, 0.125f, 0.75f, 0, 0, 0, 0};
        float b[N] = {0.5f, 0.5f,  0.5f,   0.5f,  0, 0, 0, 0};
        check_mac(a, b, "sub-unity");
    }
    { // Negative values and mixed signs
        float a[N] = {-1.5f, 2.5f, -3.5f, 4.5f, -0.5f, 6.0f, -7.0f, 8.0f};
        float b[N] = {2.5f, -3.5f, 4.5f, -5.5f, 2.0f, -1.5f, 3.0f, -2.0f};
        check_mac(a, b, "mixed-sign");
    }
    { // Perfect cancellation: +x*y - x*y == 0
        float a[N] = {3.0f, -3.0f, 0, 0, 0, 0, 0, 0};
        float b[N] = {2.0f,  2.0f, 0, 0, 0, 0, 0, 0};
        check_mac(a, b, "cancellation");
    }
    { // Underflow: product below 2^-8 flushes to zero
        lns_t a = lns_t::from_float(1.0f / 16.0f);
        lns_t b = lns_t::from_float(1.0f / 32.0f); // product 2^-9 < 2^-8
        lns_t p = a * b;
        if (!p.zero) {
            failures++;
            std::cout << "FAIL [underflow] 2^-9 product should flush to zero, got " << p.to_float() << std::endl;
        }
    }
    { // Overflow: product above 2^7.875 saturates to the max grid value
        lns_t a = lns_t::from_float(128.0f);
        lns_t b = lns_t::from_float(128.0f);
        lns_t p = a * b;
        if (p.zero || p.exponent.to_int() != EXP_MAX || p.sign != 0) {
            failures++;
            std::cout << "FAIL [overflow] expected saturation to EXP_MAX, got exp=" << p.exponent.to_int() << std::endl;
        }
    }
    { // from_float / to_float round trip stays within half a grid step (~4.4%)
        const float vals[] = {0.00390625f, 0.1f, 0.5f, 0.9f, 1.0f, 1.5f, 3.14159f, 42.0f, 234.0f,
                              -0.00390625f, -0.1f, -0.5f, -1.0f, -3.5f, -100.0f};
        for (float v : vals) {
            float rt = lns_t::from_float(v).to_float();
            if (std::fabs(rt - v) > 0.0444 * std::fabs(v)) {
                failures++;
                std::cout << "FAIL [round-trip] " << v << " -> " << rt << std::endl;
            }
        }
    }
}

// The 8x8 matrix quantization-error experiment from the original testbench,
// upgraded from print-only to asserted.
static void matrix_test() {
    double matrixA[N][N], matrixB[N][N];
    std::mt19937 rng(7);
    std::uniform_real_distribution<double> dist(1.0, 10.5);
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) { matrixA[i][j] = dist(rng); matrixB[i][j] = dist(rng); }

    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            float row_a[N], col_b[N];
            for (int k = 0; k < N; k++) { row_a[k] = float(matrixA[i][k]); col_b[k] = float(matrixB[k][j]); }
            check_mac(row_a, col_b, "matrix");
        }
    }
}

static void randomized_tests(int trials) {
    std::mt19937 rng(42); // deterministic
    // exponents chosen so products stay inside the representable range
    std::uniform_real_distribution<float> log_mag(-3.5f, 3.5f);
    std::uniform_int_distribution<int> sign_dist(0, 1);
    std::uniform_int_distribution<int> zero_dist(0, 9); // ~10% zeros

    double max_rel = 0.0, sum_rel = 0.0;
    int rel_count = 0;

    for (int t = 0; t < trials; t++) {
        float a[N], b[N];
        lns_t a_lns[N], b_lns[N], result;
        double golden = 0.0, sum_abs = 0.0;

        for (int i = 0; i < N; i++) {
            a[i] = (zero_dist(rng) == 0) ? 0.0f
                 : (sign_dist(rng) ? -1.0f : 1.0f) * std::pow(2.0f, log_mag(rng));
            b[i] = (zero_dist(rng) == 0) ? 0.0f
                 : (sign_dist(rng) ? -1.0f : 1.0f) * std::pow(2.0f, log_mag(rng));
            a_lns[i] = lns_t::from_float(a[i]);
            b_lns[i] = lns_t::from_float(b[i]);
            double p = double(a_lns[i].to_float()) * double(b_lns[i].to_float());
            golden += p;
            sum_abs += std::fabs(p);
        }

        mac_array(a_lns, b_lns, result);
        golden = clamp_repr(golden);
        double dut = result.to_float();
        double err = std::fabs(dut - golden);
        double tol = tolerance(golden, sum_abs);

        if (err > tol) {
            failures++;
            if (failures <= 10) {
                std::cout << "FAIL [random trial " << t << "] dut=" << dut
                          << " golden=" << golden << " err=" << err << " tol=" << tol << std::endl;
            }
        }
        if (std::fabs(golden) > 0.1) { // relative error only meaningful away from zero
            double rel = err / std::fabs(golden);
            max_rel = std::max(max_rel, rel);
            sum_rel += rel;
            rel_count++;
        }
    }

    std::cout << "Randomized trials: " << trials
              << "  max rel err: " << max_rel * 100 << "%"
              << "  mean rel err: " << (sum_rel / rel_count) * 100 << "%" << std::endl;
}

int main() {
    directed_tests();
    matrix_test();
    randomized_tests(10000);

    if (failures) {
        std::cout << "FAILED: " << failures << " check(s) out of tolerance." << std::endl;
        return 1;
    }
    std::cout << "All tests PASSED." << std::endl;
    return 0;
}
