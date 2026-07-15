// Host-side test-vector generator for the mac_nxn_array PYNQ-Z2 bring-up.
//
// Why this exists: the cosim testbench (silicon/tb/mac_nxn_cosim_tb.cpp) only
// runs inside Vitis HLS's cosim flow (SystemC/RTL simulator) — it cannot be
// pointed at real board DDR. To exercise the bitstream on hardware we need
// the SAME matrices and the SAME expected results as raw DDR-layout bytes
// that a PYNQ notebook can memcpy straight into an allocated buffer. So this
// program replays the cosim testbench's RNG calls byte-for-byte (same seeds,
// same distributions, same call order) to regenerate identical matrices,
// quantizes them the same way, runs the identical C golden model
// (mac_nxn_array from silicon/src/mac_silicon.cpp — the exact source that was
// synthesized), and dumps A, B, and the expected result as flat 320-byte
// files. On the board the RTL result is compared byte-for-byte against
// expected: the LNS grid + a bit-exact HLS datapath means there is no
// tolerance band here (unlike the float-vs-quantized tolerance check the
// cosim testbench applies against the *unquantized* golden matmul).
//
// Kept intentionally dumb: no CLI args, no config file, one binary, one run.

#include "mac.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <string>

typedef LNS<B, Q, R, Gamma> lns_t;

// DDR layout contract (verified against the generated RTL: WSTRB = 31 << offset):
// each LNS element is [sign][zero][exponent][quotient][remainder], one byte
// per field, in declaration order, memcpy-compatible with the host struct.
// Verify that fact holds for THIS toolchain/ABI before trusting any fwrite.
static void check_layout() {
    if (sizeof(lns_t) != 5) {
        std::fprintf(stderr,
            "FATAL: sizeof(LNS<%d,%d,%d,%d>) == %zu, expected 5. "
            "DDR layout assumption is wrong for this compiler/ABI -- do not "
            "trust the generated vectors.\n",
            (int)B, (int)Q, (int)R, (int)Gamma, sizeof(lns_t));
        std::exit(1);
    }
}

static void write_matrix(const std::string& path, const lns_t m[N][N]) {
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) { std::perror(path.c_str()); std::exit(1); }
    size_t n = std::fwrite(m, sizeof(lns_t), N * N, f);
    std::fclose(f);
    if (n != (size_t)(N * N)) {
        std::fprintf(stderr, "FATAL: short write to %s\n", path.c_str());
        std::exit(1);
    }
}

static void quantize(const float f[N][N], lns_t out[N][N]) {
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++)
            out[i][j] = lns_t::from_float(f[i][j]);
}

// Quantize, run the golden C model, and emit case<idx>_{a,b,expected}.bin.
static void emit_case(int idx, const float fa[N][N], const float fb[N][N],
                       const std::string& out_dir) {
    lns_t a[N][N], b[N][N], r[N][N];
    quantize(fa, a);
    quantize(fb, b);
    mac_nxn_array(a, b, r);

    char base[64];
    std::snprintf(base, sizeof(base), "case%d", idx);
    write_matrix(out_dir + "/" + base + "_a.bin", a);
    write_matrix(out_dir + "/" + base + "_b.bin", b);
    write_matrix(out_dir + "/" + base + "_expected.bin", r);

    std::printf("  case%d written (%s)\n", idx, base);
}

int main() {
    check_layout();

    const std::string out_dir = "../board/vectors";  // run from silicon/host/ (build_and_run.sh does)

    std::printf("Generating test vectors into %s\n", out_dir.c_str());

    int idx = 0;

    // Case 0 -- directed: original report's 8x8 experiment values, uniform
    // 1.0..10.5. RNG call order (fa then fb, interleaved per element) must
    // match silicon/tb/mac_nxn_cosim_tb.cpp exactly or the matrices diverge.
    {
        float fa[N][N], fb[N][N];
        std::mt19937 rng(7);
        std::uniform_real_distribution<float> dist(1.0f, 10.5f);
        for (int i = 0; i < N; i++)
            for (int j = 0; j < N; j++) { fa[i][j] = dist(rng); fb[i][j] = dist(rng); }
        emit_case(idx++, fa, fb, out_dir);
    }

    // Case 1 -- directed: all zeros in -> exact zeros out.
    {
        float fa[N][N] = {{0}}, fb[N][N] = {{0}};
        emit_case(idx++, fa, fb, out_dir);
    }

    // Cases 2..9 -- 8 randomized matrices, same value distribution and same
    // single shared RNG instance (seed 42) as the cosim testbench: magnitudes
    // 2^uniform(-3.5,3.5), random sign, ~10% exact zeros.
    {
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
            emit_case(idx++, fa, fb, out_dir);
        }
    }

    // Manifest so the PYNQ notebook doesn't have to hardcode the case count
    // or labels -- one source of truth for "what cases exist".
    {
        FILE* f = std::fopen((out_dir + "/manifest.json").c_str(), "w");
        if (!f) { std::perror("manifest.json"); std::exit(1); }
        std::fprintf(f, "{\n  \"matrix_bytes\": %d,\n  \"n\": %d,\n  \"element_bytes\": %d,\n  \"cases\": [\n",
                     N * N * (int)sizeof(lns_t), (int)N, (int)sizeof(lns_t));
        const char* labels[10] = {
            "directed-uniform-1..10.5", "directed-all-zero",
            "random-0", "random-1", "random-2", "random-3",
            "random-4", "random-5", "random-6", "random-7"
        };
        for (int i = 0; i < idx; i++) {
            std::fprintf(f, "    {\"name\": \"case%d\", \"label\": \"%s\"}%s\n",
                         i, labels[i], (i + 1 < idx) ? "," : "");
        }
        std::fprintf(f, "  ]\n}\n");
        std::fclose(f);
    }

    std::printf("Done: %d cases, %d vector files (320 bytes each), manifest.json written.\n", idx, idx * 3);
    return 0;
}
