"""lns_mul unit test: every product must match the C multiply() bit-exactly.

Combinational DUT, so we deposit inputs, let delta-time settle, and compare the
16-bit output word against the golden 5-byte element re-packed to 16 bits.
"""

import random

import cocotb
from cocotb.triggers import Timer

from lns_golden import (make_element, zero_element, c5_to_sv16, sv16_to_c5,
                        golden_mul, decode)


def _rand_elem(rng):
    if rng.random() < 0.1:
        return zero_element()
    return make_element(rng.randint(0, 1), rng.randint(-64, 63))


async def _check(dut, a5, b5):
    dut.a.value = c5_to_sv16(a5)
    dut.b.value = c5_to_sv16(b5)
    await Timer(1, unit="ns")
    got = int(dut.p.value)
    exp = c5_to_sv16(golden_mul(a5, b5))
    assert got == exp, (
        f"{decode(a5)} * {decode(b5)} -> dut {decode(sv16_to_c5(got))} "
        f"(0x{got:04x}) != golden {decode(golden_mul(a5, b5))} (0x{exp:04x})")


@cocotb.test()
async def mul_random(dut):
    rng = random.Random(0xA1)
    n = 2000
    for _ in range(n):
        await _check(dut, _rand_elem(rng), _rand_elem(rng))
    dut._log.info(f"lns_mul: {n} random products matched the C golden")


@cocotb.test()
async def mul_edges(dut):
    # EXP_MAX saturation, EXP_MIN underflow, exact zero, unit, mixed signs.
    edges = [make_element(0, 63), make_element(1, 63),
             make_element(0, -64), make_element(1, -64),
             make_element(0, 0), make_element(1, 0),
             make_element(0, 32), make_element(1, -32),
             zero_element()]
    for a in edges:
        for b in edges:
            await _check(dut, a, b)
    dut._log.info(f"lns_mul: {len(edges)**2} directed edge products matched")
