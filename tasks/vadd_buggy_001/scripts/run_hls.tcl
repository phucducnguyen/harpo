# HARPO — buggy vadd repair target (Week 3). Same flow as vadd_001.
#   Usage:  cd tasks/vadd_buggy_001/scripts && vitis_hls -f run_hls.tcl
# Expect csim to FAIL until the kernel is repaired.

set script_dir [file dirname [file normalize [info script]]]
set task_dir   [file normalize $script_dir/..]

set part   [expr {[info exists ::env(LS_PART)]   ? $::env(LS_PART)   : "xc7z020clg400-1"}]
set period [expr {[info exists ::env(LS_PERIOD)] ? $::env(LS_PERIOD) : 10.0}]

open_project -reset vadd_proj
set_top vadd
add_files     $task_dir/src/vadd.cpp
add_files -tb $task_dir/tb/tb_vadd.cpp

open_solution -reset "sol1"
set_part $part
create_clock -period $period -name default

csim_design
# csynth_design   ;# don't synth a kernel that fails csim — budget discipline

exit
