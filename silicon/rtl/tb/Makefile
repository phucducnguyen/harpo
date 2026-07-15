# Cocotb bench for the hand-written LNS RTL. `make` runs everything:
#   lns_mul + lns_add8 element-level unit tests, then the lns_matmul_8x8 top
#   (committed vectors + random) — all against the C golden via libgolden.so.
#
# Prerequisites (see ../README.md): the sibling .venv (cocotb) and Icarus are
# put on PATH automatically — Icarus from wherever it already is, else the
# documented user-space install at ~/tools/iverilog.

# Sibling venv (script-relative, no absolute paths baked in).
VENV_BIN    := $(abspath ../.venv/bin)
IVERILOG_ON_PATH := $(shell command -v iverilog 2>/dev/null)
ifeq ($(IVERILOG_ON_PATH),)
  IVL_BIN   := $(HOME)/tools/iverilog/bin
  SIM_ENV   := PATH="$(VENV_BIN):$(IVL_BIN):$$PATH"
else
  SIM_ENV   := PATH="$(VENV_BIN):$$PATH"
endif

# Golden model: the SAME C sources that were synthesized, as a shared library.
GOLDEN_SRC := ../../src/mac_silicon.cpp \
	../../../tasks/lns_mac_001/src/add_unit.cpp \
	../../../tasks/lns_mac_001/src/mul_unit.cpp
GOLDEN_INC := -I../../../tasks/lns_mac_001/src -I../../../.deps/hls_types/include

.PHONY: all mul add8 matmul clean

all: mul add8 matmul

libgolden.so: $(GOLDEN_SRC)
	g++ -shared -fPIC -O2 -o $@ $(GOLDEN_SRC) $(GOLDEN_INC)

mul: libgolden.so
	$(SIM_ENV) $(MAKE) -f sim.mk COCOTB_TOPLEVEL=lns_mul COCOTB_TEST_MODULES=test_mul SIM_BUILD=sim_build/mul

add8: libgolden.so
	$(SIM_ENV) $(MAKE) -f sim.mk COCOTB_TOPLEVEL=lns_add8 COCOTB_TEST_MODULES=test_add8 SIM_BUILD=sim_build/add8

matmul: libgolden.so
	$(SIM_ENV) $(MAKE) -f sim.mk COCOTB_TOPLEVEL=lns_matmul_8x8 COCOTB_TEST_MODULES=test_matmul SIM_BUILD=sim_build/matmul

clean:
	rm -rf sim_build libgolden.so results.xml __pycache__
