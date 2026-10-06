"""Contract tests for the GGUF parser's tensor-size derivation.

A tensor's byte length must come from the NEXT tensor's offset, not from a
formula. That was a real bug: `TensorEntry.nbytes` computed the TQ2_0 size
(n_elements // 256 * 66) for every tensor regardless of type, which undersized
the 402 pq2_0 tensors (34/128 B/elem, not 66/256) and wildly mis-sized the 1-D
F32 norms. The resulting identity copy came out 210 MB too large and failed its
hash check, which is how the bug was caught.

These tests pin the derivation against the real reference file.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "model_quantization", "pq2"))
import pq2_0_codec as C  # noqa: E402
import pq2_gguf as G  # noqa: E402

REFERENCE = (
    r"C:\Users\downl\Desktop\SO8T\gguf_models\Hikari07jp"
    r"\Ternary-Bonsai-2-27B-Abliterated-GGUF\Ternary-Bonsai-2-27B-Abliterated-PQ2_0.gguf"
)

needs_reference = pytest.mark.skipif(
    not os.path.exists(REFERENCE), reason="reference GGUF not present"
)


@pytest.fixture(scope="module")
def ref():
    if not os.path.exists(REFERENCE):
        pytest.skip("reference GGUF not present")
    with G.GGUFFile.open(REFERENCE) as f:
        yield f, os.path.getsize(REFERENCE)


@needs_reference
def test_header_geometry(ref):
    f, size = ref
    assert f._data_start == 11_120_992
    assert len(f.tensors) == 851
    assert len(f.kv) == 49
    assert f._file_size == size == 7_206_168_928


@needs_reference
def test_tensor_sizes_sum_to_exactly_the_data_region(ref):
    """The invariant the writer depends on: no gap, no overlap, no remainder."""
    f, size = ref
    data_len = size - f._data_start
    assert sum(t.size for t in f.tensors) == data_len


@needs_reference
def test_tensor_offsets_are_contiguous(ref):
    f, _ = ref
    off = 0
    for t in f.tensors:
        assert t.offset == off, f"gap before {t.name}: {t.offset} != {off}"
        off += t.size
    assert off == os.path.getsize(REFERENCE) - f._data_start


@needs_reference
def test_pq2_0_size_is_exactly_blocks_times_34(ref):
    """pq2_0 is dense: no padding inside a tensor, size == n_elements/128 * 34."""
    f, _ = ref
    pq2 = [t for t in f.tensors if G.is_pq2_0(t)]
    assert len(pq2) == 402
    for t in pq2:
        assert t.n_elements % C.QK_PQ2 == 0
        assert t.size == (t.n_elements // C.QK_PQ2) * C.BLOCK_BYTES, t.name


@needs_reference
def test_f32_norms_are_one_dimensional_and_not_block_quantized(ref):
    """The tensors the old formula got wrong: 1-D F32 norms."""
    f, _ = ref
    norms = [t for t in f.tensors if t.ggml_type == 0]
    assert norms, "expected F32 tensors in this file"
    for t in norms:
        assert t.size == t.n_elements * 4, t.name


@needs_reference
def test_every_size_is_positive_and_bounded(ref):
    f, size = ref
    data_len = size - f._data_start
    for t in f.tensors:
        assert t.size > 0, t.name
        assert t.offset + t.size <= data_len, t.name


def test_hand_built_entry_falls_back_to_the_formula():
    """A TensorEntry with no derived size still reports something sane."""
    t = G.TensorEntry("x", 1, (256,), 35, 0, 256, 0)
    assert t.nbytes > 0
