# 10 ns (100 MHz) target for the out-of-context run. The design is single-clock,
# fully synchronous; only the clock needs constraining for a datapath timing
# check. Input/output delays are left default (OOC): we are measuring the
# internal path, not a board-level I/O budget.
create_clock -period 10.000 -name clk [get_ports clk]
