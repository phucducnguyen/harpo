# HARPO silicon workspace — carries the HARPO-fixed lns_mac_001 through the
# stages the agent deliberately stops short of:
#   csim (tb sanity) -> csynth -> C/RTL co-simulation -> export_design -flow impl
# export -flow impl runs real Vivado synthesis + place & route out-of-context,
# replacing the csynth *estimates* with measured post-route utilization/timing.
#
# Sources are referenced IN PLACE (nothing copied) from the task's src/,
# except mac: src/mac_silicon.cpp is the case-study winner with ONE documented
# deviation (ap_ctrl_none -> s_axilite control; see its header). Cosim cannot
# drive an ap_ctrl_none top that isn't fully II=1-pipelined, and the PYNQ-Z2
# overlay needs AXI-Lite control anyway.
#
# Run: cd silicon && vitis_hls -f run_silicon.tcl
# Post-route report lands in:
#   proj_lns_silicon/sol_pynqz2/impl/report/verilog/export_impl.rpt

set ROOT     [file normalize ..]
set TASK_SRC $ROOT/tasks/lns_mac_001/src
set MAC_SRC  src/mac_silicon.cpp
set CFLAGS   "-I$TASK_SRC"

open_project -reset proj_lns_silicon
set_top mac_nxn_array
add_files $TASK_SRC/add_unit.cpp -cflags $CFLAGS
add_files $TASK_SRC/mul_unit.cpp -cflags $CFLAGS
add_files $MAC_SRC -cflags $CFLAGS
add_files -tb tb/mac_nxn_cosim_tb.cpp -cflags $CFLAGS

open_solution -reset sol_pynqz2
set_part xc7z020clg400-1
create_clock -period 10.0

csim_design
csynth_design

# ap_ctrl_none tops are not always cosim-able; don't let a protocol limitation
# kill the place & route leg — record the outcome and continue either way.
set cosim_ok 1
if {[catch {cosim_design -rtl verilog} err]} {
    set cosim_ok 0
    puts "COSIM_FAILED: $err"
}

export_design -flow impl -rtl verilog -format ip_catalog

puts "SILICON_RUN_DONE cosim_ok=$cosim_ok"
exit
