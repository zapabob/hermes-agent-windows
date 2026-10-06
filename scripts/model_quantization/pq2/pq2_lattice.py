"""TQ2_0 ternary lattice codec — REFERENCE ONLY, DO NOT POINT AT THE PQ2_0 GGUF.

READ THIS FIRST
---------------
This module implements the *git fork's* TQ2_0 type
(`GGML_TYPE_TQ2_0 = 35`, ggml/include/ggml.h:425 in
the local llama.cpp fork). That fork has
GGML_TYPE_COUNT = 49 and CANNOT open Ternary-Bonsai-2-27B-Abliterated-PQ2_0.gguf
at all.

The PQ2_0 file's weights use ggml type **142** (`pq2_0`, 17/64 bytes per element)
plus `prism.hadamard.*` metadata: the weights are stored in a normalized
Sylvester Walsh-Hadamard basis (block 1024, last dim) with an explicit ±1 sign
vector per row group. That is a different codec with a different block layout
and a transform that must be undone before any weight-space edit is meaningful.

Using this module on the PQ2_0 file would silently corrupt it. See
_docs/2026-10-01_pq2_abliteration_GroundTruth.md for the measured facts.

The block format and quantizer below are transcribed from the git fork, which is
the only implementation whose source is available:

  ggml/src/ggml-common.h:288-292
      typedef struct {
          uint8_t qs[QK_K/4];   // 2 bits per element
          ggml_half d;
      } block_tq2_0;
      static_assert(sizeof(block_tq2_0) == sizeof(ggml_half) + QK_K/4, ...);
  ggml/src/ggml-common.h:89       #define QK_K 256
  ggml/include/ggml.h:425         GGML_TYPE_TQ2_0 = 35
  ggml/src/ggml.c:941-944         type_name "tq2_0", blck_size QK_K, type_size sizeof(block_tq2_0)
  ggml/src/ggml-quants.c:2441-2471  quantize_row_tq2_0_ref
  ggml/src/ggml-cpu/ggml-cpu.c:423-428  from_float/vec_dot/vec_dot_type Q8_K

The lattice itself: values quantize to the TERNARY set {-1, 0, +1} (a 3-level
lattice, not binary 2-bit), and a block carries ONE shared fp16 scale `d` =
max|x| over the block. Dequant is therefore exactly `deq(code) * d`. Dequantize
to float and dequantize to fp16 have NO intermediate rounding, so re-quantizing
a GGUF's own payload back out is a fixed point of this codec — which is the
property the abliteration pipeline relies on to keep block scales and file size
byte-identical.

PACKING ORDER (this is the part that is easy to get wrong)
---------------------------------------------------------
In quantize_row_tq2_0_ref the value index is `m + n*32` for m in [0,32) and
n in [0,4), and the 2-bit code goes at `qs[j + m] << (2*n)`. So the element index
within a block is (m + n*32), and the bit position within the byte is 2*n.
Consequence: element i is stored in byte i%32 ... see `codes_to_floats` for the
executed, round-trip-verified unpacker.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

# --- Constants, all transcribed from the fork -------------------------------
QK_K = 256           # ggml-common.h:89
BLK_SIZE = QK_K      # ggml.c:943  blck_size
CODE_BYTES = QK_K // 4   # 64 bytes of 2-bit codes per block
GGML_TYPE_TQ2_0 = 35     # ggml.h:425
TYPE_NAME = "tq2_0"     # ggml.c:942
# Per 256 weights: 64 code bytes + 2 scale bytes = 66 bytes -> 2.0625 bpw,
# matching the fork's own "TQ2_0 - 2.06 bpw ternary" label in FileType.kt:49.

# The ternary code set: quantize_row_tq2_0_ref maps -1,0,+1 -> 0,1,2.
CODE_MIN, CODE_MID, CODE_MAX = 0, 1, 2
CODES = (0, 1, 2)    # dequantized value = (code - 1)


def deq(code: int) -> float:
    """Map a 2-bit code to its ternary dequantized value: 0->-1, 1->0, 2->+1."""
    if code < 0 or code > 3:
        raise ValueError(f"code out of range: {code}")
    return float(code - 1)


def quantize_block(x: list[float], d: float | None = None) -> tuple[bytes, float]:
    """Quantize one 256-element block, mirroring quantize_row_tq2_0_ref.

    `d` may be passed to hold the scale FIXED (the abliteration invariant: block
    scales must not change). When given, the caller has already chosen it and
    this function must not recompute amax.
    """
    if len(x) != QK_K:
        raise ValueError(f"block must be {QK_K} elements, got {len(x)}")
    if d is None:
        amax = 0.0
        for v in x:
            a = abs(v)
            if a > amax:
                amax = a
        d = amax
    d = float(d)
    if d == 0.0:
        d = 0.0
    # The C code computes id = 1/d and multiplies; a zero scale makes id 0 and
    # every code becomes lroundf(0)+1 = 1 (the zero code). Match that.
    id_ = 1.0 / d if d else 0.0

    out = bytearray(CODE_BYTES)
    for i in range(QK_K):
        # lroundf is half-away-from-zero; Python round() is banker's rounding,
        # so use floor(v+0.5) for positives and ceil(v-0.5) for negatives.
        v = x[i] * id_
        xi = (int(math.floor(v + 0.5)) if v >= 0 else int(math.ceil(v - 0.5))) + 1
        b_i, n_i = _byte_nibble(i)
        out[b_i] |= (xi & 3) << (2 * n_i)
    return bytes(out), d



def _byte_nibble(i: int) -> tuple[int, int]:
    """Element index -> (byte index in qs, 2-bit field index).

    Transcribed from quantize_row_tq2_0_ref: the outer loop steps j by 32 over
    the 64 code bytes, the middle loop walks m in [0,32), and field n of byte
    j+m carries element ``(j//32)*128 + m + n*32``. Inverting that:

        byte   = (i // 128) * 32 + (i % 128) % 32
        nibble = (i % 128) // 32
    """
    return (i // 128) * 32 + (i % 128) % 32, (i % 128) // 32


def codes_to_floats(qs: bytes, d: float) -> list[float]:
    """Unpack 64 code bytes into 256 dequantized values (exact inverse)."""
    if len(qs) != CODE_BYTES:
        raise ValueError(f"expected {CODE_BYTES} code bytes, got {len(qs)}")
    out = [0.0] * QK_K
    for i in range(QK_K):
        b_i, n_i = _byte_nibble(i)
        out[i] = deq((qs[b_i] >> (2 * n_i)) & 3)
    return [v * d for v in out]


def floats_to_codes(values: list[float], d: float) -> bytes:
    """Pack 256 values into 64 code bytes given a FIXED scale d.

    Inverse of codes_to_floats. With d chosen as max|x|, this is a fixed point:
    quantize(dequantize(block)) == block.
    """
    if len(values) != QK_K:
        raise ValueError(f"expected {QK_K} values, got {len(values)}")
    out = bytearray(CODE_BYTES)
    if d == 0.0:
        return bytes(out)
    id_ = 1.0 / d
    for i in range(QK_K):
        xi = int(round(values[i] * id_)) + 1
        b_i, n_i = _byte_nibble(i)
        out[b_i] |= (xi & 3) << (2 * n_i)
    return bytes(out)


def abliterate_block(
    qs: bytes,
    d: float,
    direction: list[float],
    amplitude: float,
    unbiased: bool = True,
) -> tuple[bytes, int]:
    """Project a steering delta onto the ternary lattice, editing the codes in place.

    Reproduces the abliteration contract the Ternary-Bonsai model card states:
    edit the 2-bit codes directly, hold every block scale fixed, and keep the
    file byte-size identical.

      1. Read current dequantized weights w = deq(code) * d.
      2. Unit direction r = direction / |direction|; desired shift s_j = amplitude * r_j.
      3. Reachable neighbours at a frozen scale are w_j +/- (2*d) along the code
         axis, because the ternary set is {-d, 0, +d} (codes 0,1,2).
      4. Accept the neighbour minimizing |w_j - s_j|: greedy nearest lattice point.
      5. UNBIASED ROUNDING: on an exact tie, index parity decides, so the
         accepted step is not systematically biased toward one sign.

    Returns (new_qs, n_changed). The caller must write the ORIGINAL `d` back.
    """
    if len(direction) != QK_K:
        raise ValueError(f"direction must be {QK_K} elements, got {len(direction)}")
    if len(qs) != CODE_BYTES:
        raise ValueError(f"qs must be {CODE_BYTES} bytes, got {len(qs)}")

    norm = math.sqrt(sum(v * v for v in direction))
    if norm == 0.0 or amplitude == 0.0 or d == 0.0:
        return qs, 0
    r = [v / norm for v in direction]
    w = codes_to_floats(qs, d)

    out = bytearray(qs)
    changed = 0
    for j in range(QK_K):
        byte_i, n = _byte_nibble(j)
        code = (qs[byte_i] >> (2 * n)) & 3
        if code == 3:  # off-lattice 4th code: never touch, it would break the size contract
            continue
        cur = deq(code) * d
        target = amplitude * r[j] * d
        best_code, best_err = code, abs(cur - target)
        for cand in (code - 1, code + 1):
            if cand < CODE_MIN or cand > CODE_MAX:
                continue
            err = abs(deq(cand) * d - target)
            if unbiased and abs(err - best_err) <= 1e-9 * max(1.0, abs(best_err)):
                if (j + cand) % 2 == 0:
                    best_code, best_err = cand, err
            elif err < best_err:
                best_code, best_err = cand, err
        if best_code != code:
            out[byte_i] = (out[byte_i] & ~(3 << (2 * n))) | (best_code << (2 * n))
            changed += 1
    return bytes(out), changed
