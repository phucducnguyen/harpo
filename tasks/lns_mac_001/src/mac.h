// #ifndef MAC_H
// #define MAC_H

// #include "LNS_datatype.h"
#include "add_unit.h"
#include "mul_unit.h"


extern "C" {
    void mac_array(LNS<B, Q, R, Gamma> array_input_a[N], LNS<B, Q, R, Gamma> array_input_b[N], LNS<B, Q, R, Gamma> &result);
    void mac_nxn_array(LNS<B, Q, R, Gamma> array_input_a[N][N], LNS<B, Q, R, Gamma> array_input_b[N][N], LNS<B, Q, R, Gamma> result[N][N]);
    void mac_nxn(LNS<B, Q, R, Gamma> array_input_a[N][N], LNS<B, Q, R, Gamma> array_input_b[N][N], LNS<B, Q, R, Gamma> result[N][N]);
}


// #endif
