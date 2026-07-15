# Out-of-context synth + place & route of lns_matmul_8x8 on the PYNQ-Z2 part
# (xc7z020clg400-1) at 10 ns. Mirrors the flow silicon/ uses for the HLS kernel,
# but on hand-written RTL: no AXI, no memory ports -- just the datapath.
#
# Run (from this directory):
#   source <Xilinx install>/2025.2/Vivado/settings64.sh
#   vivado -mode batch -source run_impl.tcl
#
# Outputs land in reports/ (utilization + timing, post-route) and are the
# numbers quoted in ../README.md. Project/junk dirs are build output.

set script_dir [file dirname [file normalize [info script]]]
set src_dir    [file join $script_dir .. src]
set rpt_dir    [file join $script_dir reports]
file mkdir $rpt_dir

set part xc7z020clg400-1
set top  lns_matmul_8x8

# --- read design -----------------------------------------------------------
read_verilog -sv [list \
    [file join $src_dir lns_pkg.sv] \
    [file join $src_dir lns_mul.sv] \
    [file join $src_dir lns_add8.sv] \
    [file join $src_dir lns_mac8.sv] \
    [file join $src_dir lns_matmul_8x8.sv] ]
read_xdc [file join $script_dir clk.xdc]

# --- out-of-context synthesis ----------------------------------------------
synth_design -top $top -part $part -mode out_of_context
write_checkpoint -force [file join $rpt_dir post_synth.dcp]
report_utilization -file [file join $rpt_dir util_synth.rpt]

# --- place & route ---------------------------------------------------------
opt_design
place_design
route_design
write_checkpoint -force [file join $rpt_dir post_route.dcp]

# --- post-route reports ----------------------------------------------------
report_utilization      -file [file join $rpt_dir util_route.rpt]
report_timing_summary   -file [file join $rpt_dir timing_route.rpt]

# One-line summary to stdout so the batch log is self-describing.
set wns [get_property SLACK [get_timing_paths -delay_type max]]
puts "IMPL_DONE part=$part top=$top WNS=$wns"
