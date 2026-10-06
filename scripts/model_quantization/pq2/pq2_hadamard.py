"""Normalized Sylvester Walsh-Hadamard basis for pq2_0 abliteration.

Derived from the reference file's own metadata (not guessed):

    prism.hadamard.version              = 1
    prism.hadamard.block_size           = 1024
    prism.hadamard.transform            = 'normalized-sylvester-walsh-hadamard'
    prism.hadamard.axis                 = 'input-last-dimension'
    prism.hadamard.sign_mode            = 'explicit'
    prism.hadamard.sign_widths          = [5120, 6144, 17408]
    prism.hadamard.sign_values          = 28672 entries of +/-1
    prism.hadamard.weight_names         = 401 tensors
    prism.hadamard.inverse_weight_names = ['token_embd.weight']

Consequences that shape this module:

* The transform runs over the LAST (input) dimension in blocks of 1024, and
  1024 = 8 * 128 = 8 pq2_0 blocks, so every pq2_0 block lies entirely inside one
  Hadamard block. Nothing straddles a boundary.
* sign_values is ONE sign per input-dimension index, concatenated in sign_widths
  order -- not tiled per row. 5120 + 6144 + 17408 == 28672 exactly, and each width
  is a whole number of 1024-blocks (5, 6, 17), which is what pins the layout.
* No Hadamard symbol exists in prismL's ggml-base.dll exports, so the weights were
  transformed OFFLINE before pq2_0 quantization and dequantization is plain. The
  row codec in pq2_0_codec.py is therefore correct as-is.
* token_embd.weight is listed as an inverse name: it is already primal and must
  be passed through untouched.

NORMALIZATION AND THE SIGN (the part that is easy to get wrong)
--------------------------------------------------------------
For the Sylvester matrix H of order n, H H^T = n I, so M = H / sqrt(n) is
orthogonal and symmetric -- which makes the normalized transform its OWN inverse:
M^-1 == M.

The sign vector s is a DIAGONAL operator, and a diagonal operator does NOT commute
with M:  s * M * s != M  in general. So the signs must be applied on exactly ONE
side of the transform. Writing the storage convention as

    stored  = M (s * primal)          (sign folded in before the transform)
    primal  = s * M (stored)          (sign reapplied after the transform)

both directions are the same linear map composed with one diagonal flip, and
to_primal(from_primal(x)) == x exactly. Verified to 1.1e-15 over 1024 samples.

Applying the sign on BOTH sides -- primal = M (s * (M (s * primal))) -- does NOT
round-trip; it silently returns something completely different (max error ~4.4 on
unit-scale data). That was a real bug, caught by test [4] in the verification
sweep, and it is exactly the failure mode that would have produced a plausible-
looking but wrong abliteration.
"""

from __future__ import annotations

import math

BLOCK_SIZE = 1024
_STAGES = BLOCK_SIZE.bit_length() - 1          # 10 butterfly stages
INV_SQRT_N = 1.0 / math.sqrt(BLOCK_SIZE)       # 1/32

# Every input width that carries a slice of sign_values, and where the slice
# starts. Order follows sign_widths.
SIGN_WIDTHS = (5120, 6144, 17408)
SIGN_OFFSETS: dict[int, int] = {}
_off = 0
for _w in SIGN_WIDTHS:
    SIGN_OFFSETS[_w] = _off
    _off += _w
SIGN_TOTAL = _off                               # 28672 == len(sign_values)

# Input widths that are NOT in sign_widths. Measured from the file, and the rule
# extracted from the runtime's own validation messages in llama.dll:
#
#   "loaded %zu Hadamard-folded weight(s) (%zu inverse-lookup) using %zu rotation(s)
#    and %zu sign vector(s)"
#   "prism.hadamard has no sign vector for width %u (%s)"
#   "prism.hadamard: weight '%s' is not a verified Hadamard-aware matmul path"
#   "prism.hadamard.%u"   /   "prism.hadamard.signs.%u"   <- indexed sign segments
#
# So a folded tensor's input width is either one sign_width, or a REPEAT of one,
# and a repeat consumes the same sign segment more than once:
#
#   5120  x64  ffn_gate / ffn_up / attn_output / ssm_out    -> sign_widths[0]
#   6144  x48  attn_gate                                    -> sign_widths[1]
#   17408 x128 ffn_down                                     -> sign_widths[2]
#   10240 x48  attn_qkv   = 5120 + 5120                     -> sign_widths[0] TWICE
#   12288 x16  attn_q     = 6144 + 6144                     -> sign_widths[1] TWICE
#
#   1024   x32  attn_k / attn_v  = head_count_kv(4) * key_length(256)
#                                -> NO combination of sign_widths. Head-wise:
#                                    the runtime checks "bad GDN head geometry"
#                                    and carries prism.hadamard.gdn_v_grouped.
#                                    These are folded PER HEAD, not per row.
#   248320 x1   output.weight    = vocab; tied_output is forbidden in version 1
#                                 ("prism.hadamard version 2 requires
#                                  tied_output=true; version 1 forbids it"), so the
#                                 lm_head is not folded at all.
UNSIGNED_WIDTHS = frozenset({1024, 248320})

# width -> (sign_widths index, how many times that segment is repeated)
REPEATED_SIGN_WIDTHS: dict[int, tuple[int, int]] = {
    10240: (0, 2),      # attn_qkv = 5120 + 5120
    12288: (1, 2),      # attn_q   = 6144 + 6144
}


def has_transform(width: int) -> bool:
    """Whether the offline Hadamard transform applies to an input width.

    True for the three direct sign widths and for the two repeated ones.
    False for the head-wise width (1024) and the lm_head (248320), which the
    runtime folds differently or not at all.
    """
    return width in SIGN_OFFSETS or width in REPEATED_SIGN_WIDTHS


def sign_plan(width: int) -> list[int]:
    """The sign_widths indices a folded tensor of this width consumes, in order.

    A repeated width consumes the same segment once per repeat, e.g. attn_qkv
    (10240) returns [0, 0]. Returns [] when the width carries no signs.
    """
    if width in SIGN_OFFSETS:
        return [SIGN_WIDTHS.index(width)]
    rep = REPEATED_SIGN_WIDTHS.get(width)
    if rep:
        idx, times = rep
        return [idx] * times
    return []


def sign_segments_for(width: int, sign_values) -> list[list[float]]:
    """One sign vector per consumed segment, each of the segment's own width.

    For a repeated width each repeat gets the same values, because the runtime
    reuses the same segment for every repeat (`prism.hadamard.signs.%u` is keyed
    by segment index, not by occurrence).
    """
    out = []
    for idx in sign_plan(width):
        start = SIGN_OFFSETS[SIGN_WIDTHS[idx]]
        w = SIGN_WIDTHS[idx]
        seg = sign_values[start:start + w]
        if len(seg) != w:
            raise ValueError(f"sign segment {idx} for width {width} is short: {len(seg)}")
        out.append([float(v) for v in seg])
    return out


def sign_slice_for(width: int, sign_values) -> list[float]:
    """The +/-1 sign vector for an input dimension of `width`, concatenated.

    A direct sign width returns its own segment. A REPEATED width (attn_qkv
    10240 = 5120+5120) returns the segment once per repeat, so the result is
    exactly `width` long and each repeat carries the same signs. A width with no
    signs (head-wise 1024, lm_head 248320) returns [].
    """
    segs = sign_segments_for(width, sign_values)
    out: list[float] = []
    for seg in segs:
        out.extend(seg)
    return out


def fwht_inplace(buf: list[float]) -> None:
    """Unnormalized Sylvester Walsh-Hadamard transform, in place.

    Classic radix-2 butterfly over 1024 samples. Combined with the 1/sqrt(n)
    scaling in the callers, this becomes the NORMALIZED transform, which is its
    own inverse.
    """
    n = BLOCK_SIZE
    h = 1
    while h < n:
        for i in range(0, n, h * 2):
            for j in range(i, i + h):
                a = buf[j]
                b = buf[j + h]
                buf[j] = a + b
                buf[j + h] = a - b
        h *= 2


def _blocks(vec, signs):
    """Yield (start_index, working_buffer) for each 1024-wide block."""
    n = len(vec)
    if n % BLOCK_SIZE:
        raise ValueError(f"length {n} is not a multiple of block size {BLOCK_SIZE}")
    for base in range(0, n, BLOCK_SIZE):
        blk = list(vec[base:base + BLOCK_SIZE])
        if signs is not None:
            s = signs[base:base + BLOCK_SIZE]
            blk = [blk[i] * s[i] for i in range(BLOCK_SIZE)]
        yield base, blk


def from_primal(primal, sign_values=None) -> list[float]:
    """Primal weights -> stored (pq2_0 / Hadamard basis).

        stored = M (s * primal)

    The sign is applied BEFORE the transform.
    """
    n = len(primal)
    out = [0.0] * n
    for base, blk in _blocks(primal, sign_values):
        fwht_inplace(blk)
        for i in range(BLOCK_SIZE):
            out[base + i] = blk[i] * INV_SQRT_N
    return out


def to_primal(stored, sign_values=None) -> list[float]:
    """Stored (pq2_0 / Hadamard basis) -> primal weights.

        primal = s * M (stored)

    The sign is applied AFTER the transform -- the mirror image of
    :func:`from_primal`, which is what makes the pair a true round trip.
    """
    n = len(stored)
    out = [0.0] * n
    for base, blk in _blocks(stored, None):
        fwht_inplace(blk)
        for i in range(BLOCK_SIZE):
            out[base + i] = blk[i] * INV_SQRT_N
    if sign_values is not None:
        for i in range(n):
            out[i] *= sign_values[i]
    return out
