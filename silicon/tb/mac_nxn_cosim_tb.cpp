// Co-simulation testbench for the TOP function mac_nxn_array (8x8 LNS matmul).
//
// Why a separate testbench: the task testbench (tb/mac_tb.cpp) exercises the
// mac_array dot-product subfunction; C/RTL co-simulation replays only calls to
// the synthesis TOP, so the DUT here is mac_nxn_array itself. Golden model and
// tolerance are identical to the task testbench: double-precision MAC of the
// QUANTIZED (LNS-grid) inputs, |dut - golden| <= 5%|golden| + 1% sum|products|
// + 2^-8, saturation clamped to the representable max. Deterministic seeds.
//
// Trial count is deliberately small (directed + a handful of random matrices):
// each top call is ~2k cycles of RTL simulation; the 10k-trial statistical gate
// already ran (and stays) in csim. Cosim's job is protocol + datapath-in-RTL
// equivalence, not re-proving the error statistics.

#include "mac.h"
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <random>

typedef LNS<B, Q, R, Gamma> lns_t;

static int failures = 0;

static const double MAX_REPR = std::pow(2.0, double(EXP_MAX) / Gamma);

static double clamp_repr(double v) {
    if (v > MAX_REPR) return MAX_REPR;
    if (v < -MAX_REPR) return -MAX_REPR;
    return v;
}

static double tolerance(double golden, double sum_abs) {
    return 0.05 * std::fabs(golden) + 0.01 * sum_abs + 1.0 / 256.0;
}

// Quantize a float matrix onto the LNS grid, run the DUT top, and check every
// output element against the double-precision golden matmul of the quantized
// inputs.
static void run_case(const float fa[N][N], const float fb[N][N], const char* label) {
    lns_t a[N][N], b[N][N], r[N][N];
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            a[i][j] = lns_t::from_float(fa[i][j]);
            b[i][j] = lns_t::from_float(fb[i][j]);
        }

    mac_nxn_array(a, b, r);

    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            double golden = 0.0, sum_abs = 0.0;
            for (int k = 0; k < N; k++) {
                double p = double(a[i][k].to_float()) * double(b[k][j].to_float());
                golden += p;
                sum_abs += std::fabs(p);
            }
            golden = clamp_repr(golden);
            double dut = r[i][j].to_float();
            double err = std::fabs(dut - golden);
            double tol = tolerance(golden, sum_abs);
            if (err > tol) {
                failures++;
                if (failures <= 10)
                    std::cout << "FAIL [" << label << " (" << i << "," << j << ")] dut="
                              << dut << " golden=" << golden << " err=" << err
                              << " tol=" << tol << std::endl;
            }
        }
    }
}

int main() {
    { // Directed: the original report's 8x8 experiment values (uniform 1..10.5)
        float fa[N][N], fb[N][N];
        std::mt19937 rng(7);
        std::uniform_real_distribution<float> dist(1.0f, 10.5f);
        for (int i = 0; i < N; i++)
            for (int j = 0; j < N; j++) { fa[i][j] = dist(rng); fb[i][j] = dist(rng); }
        run_case(fa, fb, "matrix-1..10.5");
    }
    { // Directed: zeros in -> exact zeros out
        float fa[N][N] = {{0}}, fb[N][N] = {{0}};
        run_case(fa, fb, "all-zero");
    }

    // Randomized matrices, same value distribution as the task testbench:
    // magnitudes 2^[-3.5, 3.5], random signs, ~10% zeros. Deterministic seed.
    const int RANDOM_MATRICES = 8;
    std::mt19937 rng(42);
    std::uniform_real_distribution<float> log_mag(-3.5f, 3.5f);
    std::uniform_int_distribution<int> sign_dist(0, 1);
    std::uniform_int_distribution<int> zero_dist(0, 9);
    for (int t = 0; t < RANDOM_MATRICES; t++) {
        float fa[N][N], fb[N][N];
        for (int i = 0; i < N; i++)
            for (int j = 0; j < N; j++) {
                fa[i][j] = (zero_dist(rng) == 0) ? 0.0f
                         : (sign_dist(rng) ? -1.0f : 1.0f) * std::pow(2.0f, log_mag(rng));
                fb[i][j] = (zero_dist(rng) == 0) ? 0.0f
                         : (sign_dist(rng) ? -1.0f : 1.0f) * std::pow(2.0f, log_mag(rng));
            }
        run_case(fa, fb, "random");
    }

    if (failures) {
        std::cout << "FAILED: " << failures << " element(s) out of tolerance." << std::endl;
        return 1;
    }
    std::cout << "All cosim checks PASSED." << std::endl;
    return 0;
}
