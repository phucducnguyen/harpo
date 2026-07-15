"""Golden-model access and element conversion for the LNS RTL bench.

The reference is the SAME C code that was synthesized (silicon/src/mac_silicon.cpp
+ the task's add_unit/mul_unit), compiled to libgolden.so and called through
ctypes -- LNS is never re-implemented in Python. The Makefile builds the .so.

Two element encodings meet here:
  * C / vector-file layout: 5 bytes, one field per byte, in declaration order
      [sign][zero][exponent][quotient][remainder], signed fields two's-complement.
      sizeof(LNS)==5 on this ABI (verified by silicon/host/gen_vectors.cpp).
  * RTL layout: one 16-bit word, packed [15]sign [14]zero [13:7]exp(7)
      [6:3]quotient(4) [2:0]remainder(3).
The helpers below convert between them.
"""

import ctypes
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = ctypes.CDLL(os.path.join(_HERE, "libgolden.so"))

# void mac_nxn_array(LNS a[8][8], LNS b[8][8], LNS r[8][8]) -- 320-byte buffers.
_LIB.mac_nxn_array.restype = None
_LIB.mac_nxn_array.argtypes = [ctypes.c_char_p] * 3
# void multiply(const LNS&, const LNS&, LNS&) -- references == pointers.
_LIB.multiply.restype = None
_LIB.multiply.argtypes = [ctypes.c_char_p] * 3
# void adder(LNS inputs[8], LNS& out).
_LIB.adder.restype = None
_LIB.adder.argtypes = [ctypes.c_char_p] * 2

ELEM_BYTES = 5
MATRIX_BYTES = 320


def golden_matmul(a320: bytes, b320: bytes) -> bytes:
    out = ctypes.create_string_buffer(MATRIX_BYTES)
    _LIB.mac_nxn_array(a320, b320, out)
    return out.raw[:MATRIX_BYTES]


def golden_mul(a5: bytes, b5: bytes) -> bytes:
    out = ctypes.create_string_buffer(ELEM_BYTES)
    _LIB.multiply(a5, b5, out)
    return out.raw[:ELEM_BYTES]


def golden_add8(prods40: bytes) -> bytes:
    out = ctypes.create_string_buffer(ELEM_BYTES)
    _LIB.adder(prods40, out)
    return out.raw[:ELEM_BYTES]


# --- element construction / conversion -------------------------------------

def make_element(sign: int, exp: int) -> bytes:
    """A consistent 5-byte LNS element for exp in [-64, 63] (floored q, r>=0)."""
    q = exp // 8               # Python // floors toward -inf, matching the C
    r = exp - q * 8
    return bytes([sign & 1, 0, exp & 0xFF, q & 0xFF, r & 0x7])


def zero_element() -> bytes:
    return bytes([0, 1, 0, 0, 0])


def c5_to_sv16(b5: bytes) -> int:
    """Pack a 5-byte C element into the 16-bit RTL word."""
    sign = b5[0] & 1
    zero = b5[1] & 1
    exp7 = b5[2] & 0x7F        # [-64,63] fits in 7 two's-complement bits
    q4 = b5[3] & 0xF
    r = b5[4] & 0x7
    return (sign << 15) | (zero << 14) | (exp7 << 7) | (q4 << 3) | r


def sv16_to_c5(v: int) -> bytes:
    """Unpack the 16-bit RTL word back to the 5-byte C layout."""
    sign = (v >> 15) & 1
    zero = (v >> 14) & 1
    exp7 = (v >> 7) & 0x7F
    q4 = (v >> 3) & 0xF
    r = v & 0x7
    exp = exp7 - 128 if (exp7 & 0x40) else exp7    # sign-extend 7->8
    q = q4 - 16 if (q4 & 0x8) else q4              # sign-extend 4->8
    return bytes([sign, zero, exp & 0xFF, q & 0xFF, r & 0xFF])


def decode(b5: bytes) -> str:
    """Human-readable element, for failure messages."""
    sign, zero, exp, q, r = b5[0], b5[1], b5[2], b5[3], b5[4]
    if zero & 1:
        return "zero"
    exp = exp - 256 if exp >= 128 else exp
    q = q - 256 if q >= 128 else q
    return f"{'-' if sign else '+'}2^({exp}/8) [q={q} r={r}]"
