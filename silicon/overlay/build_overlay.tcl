# build_overlay.tcl
# PYNQ-Z2 overlay for HLS IP xilinx.com:hls:mac_nxn_array:1.0
# Target part xc7z020clg400-1 (no board files) -> configure PS7 by property.
# Kernel clock: 100 MHz (design closed at 10 ns; do NOT clock faster).

set OVR_DIR   [file normalize [file dirname [info script]]]
set PROJ_DIR  [file join $OVR_DIR proj_overlay]
set PART      xc7z020clg400-1
set IP_REPO   [file normalize [file join $OVR_DIR .. proj_lns_silicon sol_pynqz2 impl ip]]
set BD_NAME   mac_lns
set JOBS      8

puts "=== build_overlay: OVR_DIR=$OVR_DIR PART=$PART JOBS=$JOBS ==="

# ---------------------------------------------------------------------------
# 1. Project
# ---------------------------------------------------------------------------
create_project proj_overlay $PROJ_DIR -part $PART -force

# ---------------------------------------------------------------------------
# 2. IP repo
# ---------------------------------------------------------------------------
set_property ip_repo_paths $IP_REPO [current_project]
update_ip_catalog

# sanity: IP present?
if {[llength [get_ipdefs xilinx.com:hls:mac_nxn_array:1.0]] == 0} {
    error "HLS IP xilinx.com:hls:mac_nxn_array:1.0 not found in catalog at $IP_REPO"
}

# ---------------------------------------------------------------------------
# 3. Block design
# ---------------------------------------------------------------------------
create_bd_design $BD_NAME

# --- Zynq PS7 -------------------------------------------------------------
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7 processing_system7_0]

# Block automation: externalize DDR + FIXED_IO (no board preset -> no board files).
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" apply_board_preset "0" Master "Disable" Slave "Disable"} \
    [get_bd_cells processing_system7_0]

# PS7 config: enable HP0 slave, request 100 MHz FCLK0.
set_property -dict [list \
    CONFIG.PCW_USE_S_AXI_HP0 {1} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} \
] [get_bd_cells processing_system7_0]

# --- HLS kernel -----------------------------------------------------------
create_bd_cell -type ip -vlnv xilinx.com:hls:mac_nxn_array:1.0 mac_nxn_array_0

# ---------------------------------------------------------------------------
# 3b. AXI connections via automation (creates interconnect + proc_sys_reset,
#     clocked from FCLK_CLK0 @ 100 MHz).
# ---------------------------------------------------------------------------
# AXI-Lite control : PS M_AXI_GP0 -> IP s_axi_control
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Master "/processing_system7_0/M_AXI_GP0" Clk "Auto"} \
    [get_bd_intf_pins mac_nxn_array_0/s_axi_control]

# Master data : IP m_axi_gmem -> PS S_AXI_HP0
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Master "/mac_nxn_array_0/m_axi_gmem" Slave "/processing_system7_0/S_AXI_HP0" Clk "Auto"} \
    [get_bd_intf_pins processing_system7_0/S_AXI_HP0]

# ---------------------------------------------------------------------------
# 4. Address / validate
# ---------------------------------------------------------------------------
assign_bd_address
regenerate_bd_layout

puts "=== ADDRESS MAP (mapped segments in PS7 Data space) ==="
set axilite_base "UNKNOWN"
foreach spc [get_bd_addr_spaces] {
    foreach seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces $spc]] {
        set off [get_property offset $seg]
        set rng [get_property range $seg]
        puts "  space=$spc seg=$seg offset=$off range=$rng"
        if {[string match "*mac_nxn_array_0*s_axi_control*" $seg] || \
            [string match "*mac_nxn_array_0_Reg*" $seg]} {
            if {$off ne ""} { set axilite_base $off }
        }
    }
}
puts "=== AXI-Lite base (IP s_axi_control) = $axilite_base ==="

validate_bd_design
puts "=== validate_bd_design PASSED ==="

save_bd_design

# ---------------------------------------------------------------------------
# 4b. Wrapper + output products
# ---------------------------------------------------------------------------
set bd_file [get_files ${BD_NAME}.bd]
make_wrapper -files $bd_file -top
set wrapper [glob -nocomplain [file join $PROJ_DIR proj_overlay.gen sources_1 bd $BD_NAME hdl ${BD_NAME}_wrapper.v]]
if {$wrapper eq ""} {
    set wrapper [glob -nocomplain [file join $PROJ_DIR proj_overlay.srcs sources_1 bd $BD_NAME hdl ${BD_NAME}_wrapper.v]]
}
puts "=== wrapper: $wrapper ==="
add_files -norecurse $wrapper
set_property top ${BD_NAME}_wrapper [current_fileset]
update_compile_order -fileset sources_1

generate_target all $bd_file

# ---------------------------------------------------------------------------
# 5. Synthesis + implementation + bitstream
# ---------------------------------------------------------------------------
launch_runs impl_1 -to_step write_bitstream -jobs $JOBS
wait_on_run impl_1

set impl_status [get_property STATUS [get_runs impl_1]]
set impl_prog   [get_property PROGRESS [get_runs impl_1]]
puts "=== impl_1 STATUS=$impl_status PROGRESS=$impl_prog ==="
if {$impl_prog ne "100%"} {
    error "impl_1 did not complete (progress=$impl_prog status=$impl_status)"
}

open_run impl_1

# ---------------------------------------------------------------------------
# 6. Timing
# ---------------------------------------------------------------------------
set wns [get_property STATS.WNS [get_runs impl_1]]
puts "=== TIMING: WNS = $wns ns ==="
if {$wns ne "" && $wns < 0} {
    puts "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    puts "!!! TIMING NOT MET: WNS = $wns ns (NEGATIVE) -- FAILED TIMING !!!"
    puts "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
} else {
    puts "=== TIMING MET (WNS = $wns ns) ==="
}
report_timing_summary -max_paths 5 -file [file join $OVR_DIR timing_summary.rpt]

# Utilization
report_utilization -file [file join $OVR_DIR utilization.rpt]
puts "=== UTILIZATION (summary) ==="
puts [report_utilization -return_string]

# ---------------------------------------------------------------------------
# 7. Copy bitstream + hwh (same basename for PYNQ)
# ---------------------------------------------------------------------------
set bit_src [glob -nocomplain [file join $PROJ_DIR proj_overlay.runs impl_1 ${BD_NAME}_wrapper.bit]]
if {$bit_src eq ""} {
    set bit_src [lindex [glob -nocomplain [file join $PROJ_DIR proj_overlay.runs impl_1 *.bit]] 0]
}
puts "=== bit_src: $bit_src ==="
file copy -force $bit_src [file join $OVR_DIR mac_lns.bit]

# find .hwh (generated under .gen or .srcs hw_handoff)
set hwh_src ""
foreach base [list [file join $PROJ_DIR proj_overlay.gen] [file join $PROJ_DIR proj_overlay.srcs]] {
    set hits [glob -nocomplain -directory $base -join sources_1 bd $BD_NAME hw_handoff ${BD_NAME}.hwh]
    if {[llength $hits] > 0} { set hwh_src [lindex $hits 0]; break }
}
if {$hwh_src eq ""} {
    # broad recursive search fallback
    set hwh_src [lindex [exec find $PROJ_DIR -name ${BD_NAME}.hwh] 0]
}
puts "=== hwh_src: $hwh_src ==="
if {$hwh_src ne "" && [file exists $hwh_src]} {
    file copy -force $hwh_src [file join $OVR_DIR mac_lns.hwh]
} else {
    puts "!!! WARNING: .hwh not found; attempting write_hw_platform to extract"
    set xsa [file join $OVR_DIR mac_lns.xsa]
    write_hw_platform -fixed -include_bit -force $xsa
    # xsa is a zip; extract the hwh
    catch {exec unzip -o $xsa ${BD_NAME}.hwh -d $OVR_DIR}
    if {[file exists [file join $OVR_DIR ${BD_NAME}.hwh]]} {
        file copy -force [file join $OVR_DIR ${BD_NAME}.hwh] [file join $OVR_DIR mac_lns.hwh]
    }
}

# ---------------------------------------------------------------------------
# 8. Final report
# ---------------------------------------------------------------------------
puts "==================================================================="
puts "OVERLAY BUILD COMPLETE"
puts "  bit : [file join $OVR_DIR mac_lns.bit]"
puts "  hwh : [file join $OVR_DIR mac_lns.hwh]"
puts "  WNS : $wns ns"
puts "  AXI-Lite base address (IP s_axi_control): $axilite_base"
puts "==================================================================="

exit 0
