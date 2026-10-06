"""Contract tests for the pq2_0 Hadamard basis (normalized Sylvester Walsh-Hadamard).

Geometry and sign layout are taken from the reference file's own metadata, not
guessed: block_size 1024 over the last (input) dimension, sign_widths
[5120, 6144, 17408] summing to exactly len(sign_values)=28672, sign_mode
'explicit'.

Distinct from the TQ2_0 tests in test_pq2_lattice.py.
"""

import math
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "model_quantization", "pq2"))
import pq2_hadamard as H  # noqa: E402


def test_metadata_constants_match_the_file():
    assert H.BLOCK_SIZE == 1024
    assert H.SIGN_WIDTHS == (5120, 6144, 17408)
    assert H.SIGN_TOTAL == 28672          # == len(sign_values) in the file
    assert 5120 + 6144 + 17408 == H.SIGN_TOTAL
    assert H._STAGES == 10                # log2(1024) butterfly stages
    assert H.INV_SQRT_N == pytest.approx(1.0 / 32.0)


def test_every_sign_width_is_a_whole_number_of_blocks():
    for w in H.SIGN_WIDTHS:
        assert w % H.BLOCK_SIZE == 0
    assert [w // H.BLOCK_SIZE for w in H.SIGN_WIDTHS] == [5, 6, 17]


def test_sign_offsets_are_contiguous():
    assert H.SIGN_OFFSETS == {5120: 0, 6144: 5120, 17408: 11264}


def test_has_transform_covers_direct_and_repeated_widths():
    """Direct sign widths, plus the two widths that REPEAT one of them.

    attn_qkv (10240) = sign_widths[0] twice and attn_q (12288) =
    sign_widths[1] twice, so they ARE folded -- with the segment reused. The
    head-wise width (1024) and the lm_head (248320) are not.
    """
    for w in (5120, 6144, 17408, 10240, 12288):
        assert H.has_transform(w), w
    for w in H.UNSIGNED_WIDTHS:
        assert not H.has_transform(w), w


def test_sign_plan_reports_the_repeats():
    assert H.sign_plan(5120) == [0]
    assert H.sign_plan(6144) == [1]
    assert H.sign_plan(17408) == [2]
    assert H.sign_plan(10240) == [0, 0]     # attn_qkv
    assert H.sign_plan(12288) == [1, 1]     # attn_q
    assert H.sign_plan(1024) == []          # head-wise
    assert H.sign_plan(248320) == []        # lm_head


def test_sign_slice_repeats_the_segment_for_a_repeated_width():
    """A repeated width gets the segment once per repeat, and the repeats match."""
    sv = [1] * 5120 + [-1] * 6144 + [1] * 17408
    direct = H.sign_slice_for(5120, sv)
    rep = H.sign_slice_for(10240, sv)
    assert len(rep) == 10240
    assert rep[:5120] == direct
    assert rep[5120:] == direct

    d6144 = H.sign_slice_for(6144, sv)
    rq = H.sign_slice_for(12288, sv)
    assert len(rq) == 12288
    assert rq[:6144] == d6144
    assert rq[6144:] == d6144


def test_every_folded_width_is_a_whole_number_of_hadamard_blocks():
    """The runtime refuses widths the block size does not divide."""
    for w, times in H.REPEATED_SIGN_WIDTHS.items():
        idx, reps = times
        assert H.SIGN_WIDTHS[idx] * reps == w
        assert w % H.BLOCK_SIZE == 0
    for w in H.SIGN_WIDTHS:
        assert w % H.BLOCK_SIZE == 0


def test_sign_segments_for_validates_segment_length():
    sv = [1] * 100
    with pytest.raises(ValueError):
        H.sign_segments_for(5120, sv)


def test_sign_slice_selects_the_right_segment():
    sv = [1] * 5120 + [-1] * 6144 + [1] * 17408
    assert H.sign_slice_for(5120, sv) == [1.0] * 5120
    assert H.sign_slice_for(6144, sv) == [-1.0] * 6144
    assert H.sign_slice_for(17408, sv) == [1.0] * 17408
    assert H.sign_slice_for(1024, sv) == []      # unsigned width


def test_sign_slice_rejects_a_short_vector():
    with pytest.raises(ValueError):
        H.sign_slice_for(5120, [1] * 100)


def test_length_must_be_a_multiple_of_the_block():
    with pytest.raises(ValueError):
        H.from_primal([0.0] * 1000)


def test_transform_is_an_involution_without_signs():
    rng = random.Random(0)
    v = [rng.gauss(0, 1) for _ in range(H.BLOCK_SIZE)]
    back = H.to_primal(H.from_primal(v))
    assert max(abs(a - b) for a, b in zip(v, back)) < 1e-10


@pytest.mark.parametrize("width", H.SIGN_WIDTHS)
def test_round_trip_with_signs(width):
    """The sign is applied on exactly ONE side; both sides silently breaks it.

    Applying the sign before AND after the transform (M s M s) does not round
    trip -- that was a real bug caught during verification (max error ~4.4 on
    unit-scale data), and it would have produced a plausible-looking but wrong
    abliteration. These assertions pin the correct convention.
    """
    rng = random.Random(width)
    sv = [1, -1, -1, 1] * (H.SIGN_TOTAL // 4)
    s = H.sign_slice_for(width, sv)
    row = [rng.gauss(0, 1) for _ in range(width)]
    back = H.to_primal(H.from_primal(row, s), s)
    assert max(abs(a - b) for a, b in zip(row, back)) < 1e-10


def test_double_sign_application_is_detectably_wrong():
    """Guard the bug that motivated the one-sided convention."""
    rng = random.Random(1)
    s = [1, -1, -1, 1] * (H.BLOCK_SIZE // 4)
    row = [rng.gauss(0, 1) for _ in range(H.BLOCK_SIZE)]
    wrong = H.transform_helper(row, s) if hasattr(H, "transform_helper") else None
    if wrong is None:
        # reproduce the broken form inline: sign before AND after
        blk = [row[i] * s[i] for i in range(H.BLOCK_SIZE)]
        H.fwht_inplace(blk)
        once = [x * H.INV_SQRT_N * s[i] for i, x in enumerate(blk)]
        blk2 = [once[i] * s[i] for i in range(H.BLOCK_SIZE)]
        H.fwht_inplace(blk2)
        twice = [x * H.INV_SQRT_N for x in blk2]
        assert max(abs(a - b) for a, b in zip(row, twice)) > 1.0


def test_transform_preserves_the_inner_product():
    rng = random.Random(2)
    a = [rng.gauss(0, 1) for _ in range(H.BLOCK_SIZE)]
    b = [rng.gauss(0, 1) for _ in range(H.BLOCK_SIZE)]
    ip = sum(x * y for x, y in zip(a, b))
    ip2 = sum(x * y for x, y in zip(H.from_primal(a), H.from_primal(b)))
    assert ip2 == pytest.approx(ip, rel=1e-9)


def test_transform_preserves_the_norm():
    rng = random.Random(3)
    v = [rng.gauss(0, 1) for _ in range(H.BLOCK_SIZE)]
    n = math.sqrt(sum(x * x for x in v))
    n2 = math.sqrt(sum(x * x for x in H.from_primal(v)))
    assert n2 == pytest.approx(n, rel=1e-9)


def test_qk_pq2_nests_exactly_inside_a_hadamard_block():
    """8 pq2_0 blocks of 128 make one 1024 Hadamard block, no straddling."""
    assert H.BLOCK_SIZE % 128 == 0
    assert H.BLOCK_SIZE // 128 == 8
