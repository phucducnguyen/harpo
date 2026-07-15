"""lns_add8 unit test: the 8-way log adder vs the C adder(), bit-exact.

The 8 inputs are packed low-index-first into the 128-bit `prods` port. Inputs
are arbitrary valid LNS elements (the adder only reads sign/zero/quotient/
remainder, exactly as a real product would present them).
"""

import random

import cocotb
from cocotb.triggers import Timer

from lns_golden import (make_element, zero_element, c5_to_sv16, sv16_to_c5,
                        golden_add8, decode)


def _rand_elem(rng):
    if rng.random() < 0.1:
        return zero_element()
    return make_element(rng.randint(0, 1), rng.randint(-64, 63))


def _pack(elems):
    v = 0
    for k, e in enumerate(elems):
        v |= c5_to_sv16(e) << (16 * k)
    return v


async def _check(dut, elems):
    dut.prods.value = _pack(elems)
    await Timer(1, unit="ns")
    got = int(dut.sum.value)
    exp = c5_to_sv16(golden_add8(b"".join(elems)))
    assert got == exp, (
        "inputs [" + ", ".join(decode(e) for e in elems) + "] -> "
        f"dut {decode(sv16_to_c5(got))} (0x{got:04x}) != "
        f"golden {decode(golden_add8(b''.join(elems)))} (0x{exp:04x})")


@cocotb.test()
async def add8_random(dut):
    rng = random.Random(0xB2)
    n = 2000
    for _ in range(n):
        await _check(dut, [_rand_elem(rng) for _ in range(8)])
    dut._log.info(f"lns_add8: {n} random 8-input reductions matched the C golden")


@cocotb.test()
async def add8_edges(dut):
    z = zero_element()
    cases = [
        [z] * 8,                                              # all zero -> zero
        [make_element(0, 63)] * 8,                            # saturate high (+)
        [make_element(1, 63)] * 8,                            # saturate high (-)
        [make_element(0, -64)] * 8,                           # near underflow
        [make_element(0, 63), make_element(1, 63)] + [z] * 6,  # exact cancel -> zero
        [make_element(0, 10)] + [z] * 7,                      # single contributor
        [make_element(i % 2, i - 32) for i in range(8)],      # mixed signs/mags
        [make_element(0, 0)] * 8,                             # eight unit values
    ]
    for c in cases:
        await _check(dut, c)
    dut._log.info(f"lns_add8: {len(cases)} directed edge reductions matched")
