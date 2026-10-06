"""pq2_0 (ggml type 142) ternary codec — reverse-engineered from prismL's ggml-base.dll.

CONFIRMED BY DISASSEMBLY (2026-10-01)
--------------------------------------
The runtime build is `~/.hermes/llama/prism-b10735-842b188/bin/ggml-base.dll`
(version 0.2.0-dev, build 10735, commit 842b18804, MSVC 19.44). It exports the
pq2_0 row functions, so the block layout is read straight off the machine code
rather than guessed:

  ordinal 668  quantize_row_pq2_0_ref   RVA 0x52870
  ordinal  14  dequantize_row_pq2_0     RVA 0x34c70
  ordinal 647  quantize_pq2_0           RVA 0x41f40

Block geometry, from the quantizer's own loop:
  - `sarq $0x7, %rax` on k          -> n_blocks = k / 128, so 128 elements/block
  - `cmpl $0x80, %ebx`              -> 128 codes packed per block
  - `addq $0x22, %rdi`              -> 34 bytes per block  (0x22)
  - 34 / 128 = 0.265625 B/elem = 2.125 bpw, which matches the 17/64 bytes/elem
    measured independently from the file's tensor offsets. Exact agreement.

Field order, from the dequantizer reading a block:
  - `movzwl (%r11,%r8), %eax` then `addq $0x8, %r10` -> the fp16 scale is read
    from the FIRST 2 bytes of the block, and the code array follows it.
  - So the block is [ fp16 d (2 bytes) ][ 32 bytes of 2-bit codes ].

Code semantics (both functions agree):
  - quantize:  code = clamp(lroundf(x * (1/|amax|)) + 1, 0, 3)
  - dequantize: code is extracted with `shrl %cl` / `andl $3` (2-bit field) and
    then `decl %edx` -> value = (code - 1) * d.
  - code 0 -> -d, 1 -> 0, 2 -> +d, 3 -> +2d. Codes 0/1/2 are the ternary set;
    3 is a spare the quantizer may emit only for |x| beyond the block scale, and
    the abliteration step must never write it (see `abliterate_block`).

Scale handling: d = max|x| over the block, stored as fp16 with the exponent
clamped to the fp16 range (guards 0x7C00 / 0x7E00 in the quantizer prevent
overflow to inf/nan). A zero block writes d = 0 and all codes 1 (the zero code).

THIS IS A DIFFERENT TYPE FROM TQ2_0
-----------------------------------
`pq2_lattice.py` implements TQ2_0 = 35 (256 elems/block, 64 code bytes + fp16
scale, scale LAST) from the git fork. Do not mix them up: block size, field
order, and the element->(byte,bit) mapping all differ.
"""

from __future__ import annotations

import math
import struct

# --- geometry, all from the disassembly -------------------------------------
QK_PQ2 = 128              # elements per block      (sarq $7 -> k/128)
BLOCK_BYTES = 34          # 0x22 stride             (addq $0x22)
SCALE_BYTES = 2           # fp16 d, FIRST in block  (movzwl (%r11,%r8))
CODE_OFFSET = SCALE_BYTES  # codes start at byte 2
CODE_BYTES = BLOCK_BYTES - SCALE_BYTES   # 32
BYTES_PER_ELEM = BLOCK_BYTES / QK_PQ2     # 0.265625
BPW = BLOCK_BYTES * 8 / QK_PQ2            # 2.125
GGML_TYPE_PQ2_0 = 142

# The code set as used by this codec. 3 decodes to +2d and is a spare; the
# quantizer's clamp allows it, but abliteration must not emit it.
CODE_MIN, CODE_MAX_TERNARY = 0, 2
SPARE_CODE = 3

FP16 = struct.Struct("<e")


def deq(code: int) -> float:
    """2-bit code -> its signed multiplier. 0->-1, 1->0, 2->+1, 3->+2."""
    if code < 0 or code > 3:
        raise ValueError(f"code out of range: {code}")
    return float(code - 1)


def quantize_block(x, d: float | None = None) -> tuple[bytes, float]:
    """Quantize 128 floats into one 34-byte pq2_0 block.

    Mirrors quantize_row_pq2_0_ref. Pass `d` to hold the scale FIXED (the
    abliteration invariant: block scales must not change).
    """
    if len(x) != QK_PQ2:
        raise ValueError(f"block must be {QK_PQ2} elements, got {len(x)}")
    if d is None:
        amax = 0.0
        for v in x:
            a = abs(v)
            if a > amax:
                amax = a
        d = amax
    d = float(d)
    id_ = 1.0 / d if d else 0.0

    codes = bytearray(CODE_BYTES)
    for i in range(QK_PQ2):
        v = x[i] * id_
        # lroundf is half-away-from-zero; Python round() is banker's rounding.
        n = int(math.floor(v + 0.5)) if v >= 0 else int(math.ceil(v - 0.5))
        code = n + 1
        if code < 0:
            code = 0
        elif code > 3:
            code = 3
        codes[i >> 2] |= (code & 3) << (2 * (i & 3))
    return FP16.pack(d) + bytes(codes), d


def codes_to_floats(block: bytes, d: float | None = None) -> list[float]:
    """Unpack a 34-byte block into 128 dequantized floats.

    If `d` is omitted the fp16 scale is read from the block's first 2 bytes.
    """
    if len(block) != BLOCK_BYTES:
        raise ValueError(f"block must be {BLOCK_BYTES} bytes, got {len(block)}")
    if d is None:
        d = FP16.unpack_from(block, 0)[0]
    out = [0.0] * QK_PQ2
    base = CODE_OFFSET
    for i in range(QK_PQ2):
        out[i] = deq((block[base + (i >> 2)] >> (2 * (i & 3))) & 3) * d
    return out


def floats_to_codes(values, d: float) -> bytes:
    """Pack 128 values into the 32 code bytes, given a FIXED scale d.

    The TERNARY set is {-d, 0, +d} (codes 0/1/2). Code 3 decodes to +2d and is
    the quantizer's spare, used only for weights that exceeded the block scale at
    quantization time. Steering a row can push a value past the ternary boundary,
    and this function deliberately CLAMPS to the ternary set instead of letting
    it spill into code 3: writing the spare code would move the weight off the
    set the model was trained on.

    The clamp boundary is |x/d| = 1.5, because code = lroundf(x/d) + 1 and the
    ternary codes are 0..2. Anything beyond that saturates at the nearest ternary
    point rather than becoming +2d.
    """
    if len(values) != QK_PQ2:
        raise ValueError(f"expected {QK_PQ2} values, got {len(values)}")
    codes = bytearray(CODE_BYTES)
    if d == 0.0:
        return bytes(codes)
    id_ = 1.0 / d
    for i in range(QK_PQ2):
        v = values[i] * id_
        n = int(math.floor(v + 0.5)) if v >= 0 else int(math.ceil(v - 0.5))
        code = n + 1
        if code < 0:
            code = 0
        elif code > CODE_MAX_TERNARY:      # 2, NOT 3: never write the spare
            code = CODE_MAX_TERNARY
        codes[i >> 2] |= (code & 3) << (2 * (i & 3))
    return bytes(codes)


def abliterate_block(block: bytes, direction, amplitude: float, unbiased: bool = True):
    """Project a steering delta onto the pq2_0 ternary lattice, editing codes in place.

    The abliteration contract the Ternary-Bonsai model card states: edit the 2-bit
    codes directly, hold every block scale fixed, keep the file byte-size identical.

      1. w = deq(code) * d for the current block.
      2. r = direction / |direction|; desired shift s_j = amplitude * r_j.
      3. With the scale frozen the only reachable neighbours of code c are c-1
         and c+1 (the ternary set is {-d, 0, +d}).
      4. Accept the neighbour minimizing |w_j - s_j| — greedy nearest lattice point.
      5. UNBIASED ROUNDING: on an exact tie, the element index parity decides, so
         accepted steps are not systematically biased toward one sign.

    The spare code 3 (+2d) is never emitted: writing it would move a weight off
    the ternary set the model was trained on. The scale `d` in the returned
    block is copied through unchanged, so the caller never has to rewrite it.
    """
    if len(block) != BLOCK_BYTES:
        raise ValueError(f"block must be {BLOCK_BYTES} bytes, got {len(block)}")
    if len(direction) != QK_PQ2:
        raise ValueError(f"direction must be {QK_PQ2} elements, got {len(direction)}")

    d = FP16.unpack_from(block, 0)[0]
    norm = math.sqrt(sum(v * v for v in direction))
    if norm == 0.0 or amplitude == 0.0 or d == 0.0:
        return block, 0

    r = [v / norm for v in direction]
    codes = bytearray(block[CODE_OFFSET:])
    changed = 0
    for j in range(QK_PQ2):
        byte_i, bit_i = j >> 2, j & 3
        code = (codes[byte_i] >> (2 * bit_i)) & 3
        if code == SPARE_CODE:
            continue
        cur = deq(code) * d
        target = amplitude * r[j] * d
        best_code, best_err = code, abs(cur - target)
        for cand in (code - 1, code + 1):
            if cand < CODE_MIN or cand > CODE_MAX_TERNARY:
                continue
            err = abs(deq(cand) * d - target)
            if unbiased and abs(err - best_err) <= 1e-9 * max(1.0, abs(best_err)):
                if (j + cand) % 2 == 0:
                    best_code, best_err = cand, err
            elif err < best_err:
                best_code, best_err = cand, err
        if best_code != code:
            codes[byte_i] = (codes[byte_i] & ~(3 << (2 * bit_i))) | (best_code << (2 * bit_i))
            changed += 1
    return block[:CODE_OFFSET] + bytes(codes), changed
