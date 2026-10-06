"""Contract tests for the TQ2_0 ternary-lattice codec (git fork's type 35).

SCOPE WARNING: this covers TQ2_0 = 35 from
`C:\\Users\\downl\\Documents\\zapabob-llama-cpp`, NOT the pq2_0 (type 142) codec
used by Ternary-Bonsai-2-27B-Abliterated-PQ2_0.gguf. Those are different types
in different codebases. The pq2_0 codec is unimplemented; see
_docs/2026-10-01_pq2_abliteration_GroundTruth.md.

Behaviour contracts, transcribed from `zapabob/llama.cpp`:
  - block = 64 code bytes (2 bits/elem, 256 elems) + one fp16 scale `d`
  - codes decode to the ternary set {-1, 0, +1} (0, 1, 2; 0b11 unused)
  - quantize/dequantize must be a fixed point so re-quantization is lossless in
    structure, which is what keeps block scales and file size byte-identical
  - abliteration edits codes only, never the scale
"""
import math
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "model_quantization", "pq2"))
import pq2_lattice as L  # noqa: E402




def test_block_geometry_matches_fork():
    assert L.QK_K == 256
    assert L.CODE_BYTES == 64
    assert (L.CODE_BYTES + 2) * 8 / L.QK_K == pytest.approx(2.0625)


def test_code_set_is_ternary():
    assert (L.deq(0), L.deq(1), L.deq(2)) == (-1.0, 0.0, 1.0)
    # 0b11 is the unused fourth code. It still decodes (to +2) so the codec is
    # total over any byte pattern; the abliteration step is what refuses to
    # write it, because emitting it would move a weight off the ternary set.
    assert L.deq(3) == 2.0
    with pytest.raises(ValueError):
        L.deq(4)


@pytest.mark.parametrize("seed", range(12))
def test_requantize_is_a_fixed_point(seed):
    """The invariant the abliteration pipeline depends on."""
    rng = random.Random(seed)
    x = [rng.gauss(0, 1) for _ in range(L.QK_K)]
    qs, d = L.quantize_block(x)
    qs2, d2 = L.quantize_block(L.codes_to_floats(qs, d))
    assert qs2 == qs
    assert d2 == pytest.approx(d, abs=1e-9)


@pytest.mark.parametrize("seed", range(12))
def test_unpack_repack_inverse_over_all_codes(seed):
    """Includes the unused 0b11 code, so the codec is total."""
    rng = random.Random(seed)
    qs = bytes(rng.getrandbits(8) for _ in range(L.CODE_BYTES))
    d = rng.uniform(0.01, 3.0)
    assert L.floats_to_codes(L.codes_to_floats(qs, d), d) == qs


def test_abliteration_preserves_size_and_scale():
    rng = random.Random(7)
    x = [rng.gauss(0, 1) for _ in range(L.QK_K)]
    qs, d = L.quantize_block(x)
    direction = [rng.gauss(0, 1) for _ in range(L.QK_K)]
    qs2, changed = L.abliterate_block(qs, d, direction, amplitude=0.35)
    assert len(qs2) == L.CODE_BYTES          # file size invariant
    assert changed > 0
    # Scale is returned unchanged: abliterate_block never emits a scale, so the
    # caller writes the original d back -> block scales invariant.
    assert L.codes_to_floats(qs, d) != L.codes_to_floats(qs2, d)


@pytest.mark.parametrize("direction,amplitude", [
    ([0.0] * L.QK_K, 0.35),
    ([1.0] * L.QK_K, 0.0),
])
def test_degenerate_input_is_a_no_op(direction, amplitude):
    rng = random.Random(3)
    x = [rng.gauss(0, 1) for _ in range(L.QK_K)]
    qs, d = L.quantize_block(x)
    qs2, changed = L.abliterate_block(qs, d, direction, amplitude=amplitude)
    assert changed == 0
    assert qs2 == qs
