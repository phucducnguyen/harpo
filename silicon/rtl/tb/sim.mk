# Shared cocotb sim include. Invoked once per top-level by the master Makefile
# with COCOTB_TOPLEVEL / COCOTB_TEST_MODULES / SIM_BUILD set.
TOPLEVEL_LANG ?= verilog
SIM ?= icarus

# Prefer the sibling .venv if present (kept script-relative, no absolute paths).
VENV_BIN := $(abspath ../.venv/bin)
ifneq ($(wildcard $(VENV_BIN)/cocotb-config),)
export PATH := $(VENV_BIN):$(PATH)
endif

# The bench modules and lns_golden live here.
export PYTHONPATH := $(abspath .):$(PYTHONPATH)

RTL := $(abspath ../src)
VERILOG_SOURCES = \
	$(RTL)/lns_pkg.sv \
	$(RTL)/lns_mul.sv \
	$(RTL)/lns_add8.sv \
	$(RTL)/lns_mac8.sv \
	$(RTL)/lns_matmul_8x8.sv

include $(shell cocotb-config --makefiles)/Makefile.sim
