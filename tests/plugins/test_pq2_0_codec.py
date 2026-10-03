"""Contract tests for the pq2_0 codec (ggml type 142), reverse-engineered from
prismL's ggml-base.dll (build 10735 / commit 842b18804).

Block geometry confirmed by disassembly of quantize_row_pq2_0_ref (RVA 0x52870)
and dequantize_row_pq2_0 (RVA 0x34c70):
  128 elements/block, 34 bytes/block, fp16 scale FIRST then 32 bytes of 2-bit
  codes, code value = (code - 1) * d.

Distinct from TQ2_0 (type 35) in test_pq2_lattice.py: different block size,
different field order, different element->bit mapping.
"""

import os
import random
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tmp"))
import pq2_0_codec as C  # noqa: E402


def test_block_geometry_matches_disassembly():
    assert C.QK_PQ2 == 128          # sarq $7  -> k / 128
    assert C.BLOCK_BYTES == 34      # addq $0x22
    assert C.CODE_OFFSET == 2       # movzwl (%r11,%r8) reads the scale first
    assert C.CODE_BYTES == 32
    assert C.BYTES_PER_ELEM == pytest.approx(0.265625)   # 17/64, matches the file
    assert C.BPW == pytest.approx(2.125)
    assert C.GGML_TYPE_PQ2_0 == 142


def test_code_semantics():
    assert (C.deq(0), C.deq(1), C.deq(2), C.deq(3)) == (-1.0, 0.0, 1.0, 2.0)
    with pytest.raises(ValueError):
        C.deq(4)


@pytest.mark.parametrize("seed", range(10))
def test_codes_are_a_fixed_point_at_the_stored_fp16_scale(seed):
    """The invariant the abliteration pipeline depends on.

    The block scale is stored as fp16, so requantizing dequantized values must
    reuse that stored value. Then codes round-trip exactly, which is why editing
    codes cannot perturb any scale or the file size.
    """
    rng = random.Random(seed)
    x = [rng.gauss(0, 1) for _ in range(C.QK_PQ2)]
    blk, _ = C.quantize_block(x)
    d_stored = C.FP16.unpack_from(blk, 0)[0]
    values = C.codes_to_floats(blk)
    assert C.quantize_block(values, d=d_stored)[0] == blk


@pytest.mark.parametrize("seed", range(10))
def test_unpack_repack_inverse_over_the_ternary_codes(seed):
    """Round-trip is the identity on the ternary set {0,1,2}.

    Code 3 is the quantizer's spare (+2d) and is NOT in the ternary set, so
    `floats_to_codes` saturates it to 2 rather than reproducing it. That clamp is
    deliberate -- it is what keeps steering from writing weights off the
    ternary set the model was trained on -- but it means the pack/unpack pair is
    an identity only on codes 0..2, not over arbitrary byte patterns.
    """
    rng = random.Random(seed)
    codes = bytearray(C.CODE_BYTES)
    for i in range(C.QK_PQ2):
        # build a block containing ONLY ternary codes, by construction
        pass
    # construct via the codec itself so the codes are guaranteed ternary
    values = [rng.choice([-1.0, 0.0, 1.0]) * 0.73 for _ in range(C.QK_PQ2)]
    d = 0.73
    packed = C.floats_to_codes(values, d)
    for i in range(C.QK_PQ2):
        code = (packed[i >> 2] >> (2 * (i & 3))) & 3
        assert code in (0, 1, 2), "the packer emitted the spare code"
    assert C.floats_to_codes(C.codes_to_floats(
        C.FP16.pack(d) + packed, d), d) == packed


@pytest.mark.parametrize("seed", range(10))
def test_pack_saturates_the_spare_code(seed):
    """A value beyond the ternary boundary saturates to +2's neighbour, never 3."""
    rng = random.Random(seed)
    d = rng.uniform(0.01, 3.0)
    # deliberately push values well past the ternary boundary
    values = [rng.uniform(2.0, 6.0) * d for _ in range(C.QK_PQ2)]
    packed = C.floats_to_codes(values, d)
    for i in range(C.QK_PQ2):
        code = (packed[i >> 2] >> (2 * (i & 3))) & 3
        assert code != C.SPARE_CODE


def test_zero_block_encodes_every_weight_as_the_zero_code():
    """d == 0 makes id == 0, so every code becomes 1 (== deq 0.0).

    Each byte holds four 2-bit fields all equal to 1, i.e. 0b01010101 == 0x55.
    This matches quantize_row_pq2_0_ref, which computes lroundf(0*0)+1 = 1.
    """
    blk, d = C.quantize_block([0.0] * C.QK_PQ2)
    assert d == 0.0
    assert blk[0:2] == b"\x00\x00"
    assert set(blk[C.CODE_OFFSET:]) == {0x55}
    for i in range(C.QK_PQ2):
        assert ((blk[C.CODE_OFFSET + (i >> 2)] >> (2 * (i & 3))) & 3) == 1
    assert C.codes_to_floats(blk) == [0.0] * C.QK_PQ2


def test_abliteration_preserves_size_and_scale():
    rng = random.Random(11)
    x = [rng.gauss(0, 1) for _ in range(C.QK_PQ2)]
    blk, _ = C.quantize_block(x)
    direction = [rng.gauss(0, 1) for _ in range(C.QK_PQ2)]
    blk2, changed = C.abliterate_block(blk, direction, amplitude=0.35)
    assert len(blk2) == C.BLOCK_BYTES                      # file-size invariant
    assert blk2[0:2] == blk[0:2]                          # block-scale invariant
    assert changed > 0
    assert C.codes_to_floats(blk) != C.codes_to_floats(blk2)


@pytest.mark.parametrize("amplitude", [0.1, 0.35, 0.9, 2.0])
def test_abliteration_never_emits_the_spare_code(amplitude):
    rng = random.Random(12)
    x = [rng.gauss(0, 1) for _ in range(C.QK_PQ2)]
    blk, _ = C.quantize_block(x)
    direction = [rng.gauss(0, 1) for _ in range(C.QK_PQ2)]
    blk2, _ = C.abliterate_block(blk, direction, amplitude=amplitude)
    for i in range(C.QK_PQ2):
        code = (blk2[C.CODE_OFFSET + (i >> 2)] >> (2 * (i & 3))) & 3
        assert code != C.SPARE_CODE


@pytest.mark.parametrize("direction,amplitude", [
    ([0.0] * C.QK_PQ2, 0.35),
    ([1.0] * C.QK_PQ2, 0.0),
])
def test_degenerate_input_is_a_no_op(direction, amplitude):
    rng = random.Random(13)
    x = [rng.gauss(0, 1) for _ in range(C.QK_PQ2)]
    blk, _ = C.quantize_block(x)
    blk2, changed = C.abliterate_block(blk, direction, amplitude=amplitude)
    assert changed == 0
    assert blk2 == blk
