# Baseline implementation attempt — the archived 2024 top-level-PIPELINE design
# carried through the same out-of-context export_design -flow impl as the fixed
# design. Question under test (paper 3 §V-E / Threats): csynth estimates the
# baseline at 168.7% LUT, but the estimator measured ~2.4x pessimistic on the
# fixed design — does the baseline actually fail Vivado place & route, and at
# which stage, or does it fit after all? "Cannot place" must be a measured
# outcome, not an inference from an estimate.
#
# Interface: the task's original ap_ctrl_none top, unmodified — this pairs with
# the impl-verify winner measurement (8,527 LUT, ap_ctrl_none), NOT with the
# s_axilite silicon build. No csim/cosim: the datapath is the already-verified
# snapshot; only synthesis + implementation outcome is under test.
#
# Run: cd silicon && vitis_hls -f run_baseline_impl.tcl
# Outcome lands in run_baseline_impl.log (BASELINE_IMPL_OK/FAILED) and, on
# success, proj_lns_baseline/sol_baseline/impl/report/verilog/export_impl.rpt

set ROOT     [file normalize ..]
set TASK_SRC $ROOT/tasks/lns_mac_001/src
set CFLAGS   "-I$TASK_SRC"

open_project -reset proj_lns_baseline
set_top mac_nxn_array
add_files $TASK_SRC/add_unit.cpp -cflags $CFLAGS
add_files $TASK_SRC/mul_unit.cpp -cflags $CFLAGS
add_files $TASK_SRC/mac.cpp -cflags $CFLAGS

open_solution -reset sol_baseline
set_part xc7z020clg400-1
create_clock -period 10.0

csynth_design

if {[catch {export_design -flow impl -rtl verilog -format ip_catalog} err]} {
    puts "BASELINE_IMPL_FAILED: $err"
} else {
    puts "BASELINE_IMPL_OK"
}
puts "BASELINE_RUN_DONE"
exit
