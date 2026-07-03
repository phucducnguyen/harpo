# HARPO Gate-0 — manual HLS flow proof for vadd
#
#   Usage:  cd tasks/vadd_001/scripts && vitis_hls -f run_hls.tcl
#
# Part/clock are task-injected (env overridable), never hardcoded into the
# agent — the competition may specify a different FPGA part, tool version,
# and clock target per task.
#   LS_PART   default xc7z020clg400-1  (PYNQ-Z2, free-licensed)
#   LS_PERIOD default 10.0 ns

set script_dir [file dirname [file normalize [info script]]]
set task_dir   [file normalize $script_dir/..]

set part   [expr {[info exists ::env(LS_PART)]   ? $::env(LS_PART)   : "xc7z020clg400-1"}]
set period [expr {[info exists ::env(LS_PERIOD)] ? $::env(LS_PERIOD) : 10.0}]

puts "HARPO: part=$part period=${period}ns task=$task_dir"

open_project -reset vadd_proj
set_top vadd
add_files     $task_dir/src/vadd.cpp
add_files -tb $task_dir/tb/tb_vadd.cpp

open_solution -reset "sol1"
set_part $part
create_clock -period $period -name default

csim_design
csynth_design
# cosim_design   ;# enable only after csim + csynth are clean (slow RTL sim)

exit
