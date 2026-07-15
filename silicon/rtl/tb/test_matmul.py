"""lns_matmul_8x8 top-level test.

Replays the 10 committed board vectors (byte-exact, no tolerance -- the LNS grid
plus a bit-exact datapath means the RTL must reproduce the golden output exactly)
and a batch of random 8x8 matmuls checked against the C mac_nxn_array. Also
reports the measured cycle count for one full 8x8 matmul (start pulse -> done).
"""

import pathlib
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

from lns_golden import (golden_matmul, make_element, zero_element,
                        c5_to_sv16, sv16_to_c5, decode)

VDIR = pathlib.Path(__file__).resolve().parents[2] / "board" / "vectors"


def _pack_matrix(b320):
    v = 0
    for e in range(64):
        v |= c5_to_sv16(b320[e * 5:e * 5 + 5]) << (16 * e)
    return v


def _unpack_matrix(v):
    out = bytearray()
    for e in range(64):
        out += sv16_to_c5((v >> (16 * e)) & 0xFFFF)
    return bytes(out)


async def _reset(dut):
    dut.rst_n.value = 0
    dut.start.value = 0
    dut.a_flat.value = 0
    dut.b_flat.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def _run(dut, a320, b320):
    """Drive one matmul; return (result_bytes, cycles start->done)."""
    dut.a_flat.value = _pack_matrix(a320)
    dut.b_flat.value = _pack_matrix(b320)
    dut.start.value = 1
    await RisingEdge(dut.clk)      # start captured on this edge
    dut.start.value = 0
    cycles = 0
    while True:
        await RisingEdge(dut.clk)
        cycles += 1
        if int(dut.done.value) == 1:
            break
    # let r_flat settle for the read
    await Timer(1, unit="ns")
    return _unpack_matrix(int(dut.r_flat.value)), cycles


def _diff_report(got, exp):
    for e in range(64):
        g = got[e * 5:e * 5 + 5]
        x = exp[e * 5:e * 5 + 5]
        if g != x:
            i, j = e // 8, e % 8
            return (f"first diff at R[{i}][{j}]: dut {decode(g)} != "
                    f"golden {decode(x)}")
    return "no diff"


@cocotb.test()
async def matmul_vectors(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    cycles = None
    for c in range(10):
        a = (VDIR / f"case{c}_a.bin").read_bytes()
        b = (VDIR / f"case{c}_b.bin").read_bytes()
        exp = (VDIR / f"case{c}_expected.bin").read_bytes()
        got, cycles = await _run(dut, a, b)
        assert got == exp, f"case{c}: {_diff_report(got, exp)}"
    dut._log.info(f"lns_matmul_8x8: 10/10 committed vectors byte-exact; "
                  f"{cycles} cycles from start to done per 8x8 matmul")


@cocotb.test()
async def matmul_random(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    rng = random.Random(0xC3)
    trials = 20
    for t in range(trials):
        def elem():
            if rng.random() < 0.1:
                return zero_element()
            return make_element(rng.randint(0, 1), rng.randint(-64, 63))
        a = b"".join(elem() for _ in range(64))
        b = b"".join(elem() for _ in range(64))
        got, _ = await _run(dut, a, b)
        exp = golden_matmul(a, b)
        assert got == exp, f"random trial {t}: {_diff_report(got, exp)}"
    dut._log.info(f"lns_matmul_8x8: {trials} random 8x8 matmuls matched the C golden")
