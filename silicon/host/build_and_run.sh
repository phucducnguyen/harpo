#!/usr/bin/env bash
# Build gen_vectors against the exact synthesized kernel source (silicon/src,
# NOT tasks/lns_mac_001/src/mac.cpp -- that file redefines mac_array /
# mac_nxn_array and would clash at link time) plus the shared mul/add units,
# then run it so silicon/board/vectors/ is populated in one step.
set -euo pipefail

HARPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TASK_SRC=$HARPO/tasks/lns_mac_001/src
HLS_INC=$HARPO/.deps/hls_types/include
HOST_DIR=$HARPO/silicon/host

g++ -std=c++14 -I"$TASK_SRC" -I"$HLS_INC" -O2 \
    -o "$HOST_DIR/gen_vectors" \
    "$HOST_DIR/gen_vectors.cpp" \
    "$HARPO/silicon/src/mac_silicon.cpp" \
    "$TASK_SRC/add_unit.cpp" \
    "$TASK_SRC/mul_unit.cpp"

(cd "$HOST_DIR" && ./gen_vectors)
