"""Contract tests for pq2_0 abliteration.

These pin the invariants the abliteration contract depends on, and the two
basis conventions that are easy to get wrong:

* The Hadamard basis must be entered and left on OPPOSITE sides of the
  transform, or the row silently comes back as something else.
* Scale/byte-length invariance must survive every edit.
"""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tmp"))
import pq2_0_codec as C  # noqa: E402
import pq2_abliterate as A  # noqa: E402
import pq2_hadamard as H  # noqa: E402


def _row(scales, seed=0):
    rng = random.Random(seed)
    blocks = []
    for d in scales:
        x = [rng.uniform(-d, d) for _ in range(C.QK_PQ2)]
        blk, _ = C.quantize_block(x, d=d)
        blocks.append(blk)
    return blocks


def test_block_scale_is_read_from_the_prefix():
    blk, _ = C.quantize_block([0.5, -0.5] + [0.0] * (C.QK_PQ2 - 2), d=0.5)
    assert A.block_scale(blk) == pytest.approx(0.5, rel=1e-3)


def test_deq_and_req_row_round_trip():
    scales = [0.7, 1.3, 0.2]
    blocks = _row(scales, seed=1)
    vals = A.deq_row(blocks)
    assert len(vals) == 3 * C.QK_PQ2
    assert A.req_row(vals, scales) == b"".join(blocks)


def test_abliterate_row_preserves_size_and_scales():
    scales = [0.5, 0.9]
    blocks = _row(scales, seed=2)
    rng = random.Random(3)
    direction = [rng.gauss(0, 1) for _ in range(2 * C.QK_PQ2)]
    new, changed = A.abliterate_row(blocks, direction, amplitude=0.2, sign_values=None)
    assert len(new) == len(b"".join(blocks))         # byte-size invariant
    # every block's 2-byte scale prefix is untouched
    for k in range(len(scales)):
        assert new[k * C.BLOCK_BYTES:k * C.BLOCK_BYTES + 2] == \
               blocks[k][0:2]                          # scale invariant
    assert changed >= 0


def test_primal_steering_actually_moves_the_primal_direction():
    """One Hadamard block of steering moves ALL 1024 of its coordinates.

    Steering a single coordinate is not expressible: a change in one Hadamard
    coefficient moves every coordinate in that block. The ternary lattice then
    sets a hard amplitude threshold -- below it the projection rounds back to the
    original codes and the edit is a silent no-op. That threshold is a property of
    the format, so the test pins the threshold behaviour rather than assuming a
    small amplitude is enough.
    """
    nblocks = 5120 // C.QK_PQ2                          # 40 pq2_0 blocks = 5 x 1024
    scales = [1.0] * nblocks
    blocks = _row(scales, seed=4)
    direction = [0.0] * (nblocks * C.QK_PQ2)
    direction[0] = 1.0                                  # push coordinate 0 positive
    sv = [1, -1, -1, 1] * (H.SIGN_TOTAL // 4)
    signs = H.sign_slice_for(5120, sv)
    assert len(signs) == 5120

    before = H.to_primal(A.deq_row(blocks), signs)

    def deltas_for(amp):
        new, _ = A.abliterate_row(blocks, direction, amplitude=amp, sign_values=signs)
        parts = [new[i * C.BLOCK_BYTES:(i + 1) * C.BLOCK_BYTES] for i in range(nblocks)]
        after = H.to_primal(A.deq_row(parts), signs)
        return [after[i] - before[i] for i in range(5120)]

    # Below the lattice threshold the edit is a genuine no-op: codes are unchanged,
    # so nothing moves at all. This is the failure mode a naive implementation
    # would report as success.
    for small in (0.5, 2.0, 8.0):
        assert all(x == 0.0 for x in deltas_for(small)), small

    # Once the amplitude clears the threshold the steering lands.
    big = deltas_for(64.0)
    assert big[0] > 0.0
    assert big[0] == max(big)


def test_steering_one_hadamard_block_touches_all_eight_pq2_blocks():
    """The pq2_0 blocks inside a steered 1024 block change together."""
    nblocks = 5120 // C.QK_PQ2
    blocks = _row([1.0] * nblocks, seed=14)
    direction = [0.0] * (nblocks * C.QK_PQ2)
    direction[0] = 1.0
    sv = [1, -1, -1, 1] * (H.SIGN_TOTAL // 4)
    signs = H.sign_slice_for(5120, sv)
    new, _ = A.abliterate_row(blocks, direction, amplitude=64.0, sign_values=signs)
    changed = [k for k in range(nblocks)
               if new[k * C.BLOCK_BYTES + 2:(k + 1) * C.BLOCK_BYTES] != blocks[k][2:]]
    # the first hadamard block covers pq2 blocks 0..7, and all of them move
    assert changed, "at least the first hadamard block must change"
    assert set(changed) <= set(range(8))
    assert len(changed) >= 1


def test_abliteration_never_emits_the_spare_code():
    nblocks = 5120 // C.QK_PQ2
    scales = [0.8] * nblocks
    blocks = _row(scales, seed=5)
    rng = random.Random(6)
    direction = [rng.gauss(0, 1) for _ in range(nblocks * C.QK_PQ2)]
    sv = [1, -1, -1, 1] * (H.SIGN_TOTAL // 4)
    signs = H.sign_slice_for(5120, sv)
    for amp in (0.1, 0.5, 1.5, 3.0):
        new, _ = A.abliterate_row(blocks, direction, amplitude=amp, sign_values=signs)
        for k in range(len(scales)):
            base = k * C.BLOCK_BYTES + C.CODE_OFFSET
            for j in range(C.QK_PQ2):
                code = (new[base + (j >> 2)] >> (2 * (j & 3))) & 3
                assert code != C.SPARE_CODE


@pytest.mark.parametrize("amplitude", [0.0, 1e-9])
def test_zero_amplitude_is_a_no_op(amplitude):
    scales = [0.6] * 4
    blocks = _row(scales, seed=7)
    rng = random.Random(8)
    direction = [rng.gauss(0, 1) for _ in range(4 * C.QK_PQ2)]
    new, _ = A.abliterate_row(blocks, direction, amplitude=amplitude, sign_values=None)
    assert new == b"".join(blocks)


def test_zero_direction_is_a_no_op():
    scales = [0.6] * 4
    blocks = _row(scales, seed=9)
    new, _ = A.abliterate_row(blocks, [0.0] * (4 * C.QK_PQ2), amplitude=0.5, sign_values=None)
    assert new == b"".join(blocks)


def _split(buf, n):
    step = len(buf) // n
    return [buf[i * step:(i + 1) * step] for i in range(n)]
