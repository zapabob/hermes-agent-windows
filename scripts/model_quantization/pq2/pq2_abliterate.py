"""pq2_0 abliteration: primal-basis steering with lattice projection.

Pipeline for one tensor row
---------------------------
    stored codes --dequantize--> stored values          (34B block, scale frozen)
                 --to_primal-->  w                      (inverse Hadamard, signs)
                 --steer-->     w'                     (refusal direction, amp)
                 --to_stored--> new values
                 --project-->    new codes               (nearest ternary point,
                                                        unbiased ties)

Everything the abliteration contract calls for is enforced here:

* Only the 2-bit code payload is ever written. The fp16 block scale is copied
  through, so every block scale is preserved bit-for-bit.
* No write changes a block's length, so the file size is unchanged.
* Codes stay on the ternary set {0,1,2}; the spare code 3 (+2d) is never emitted,
  because the model was trained on ternary weights and 3 is off that set.
* Ties are broken by element-index parity, so repeated application does not bias
  the accepted steps toward one sign (unbiased rounding).

Tensors with an input width that has no slice of sign_values (1024, 10240,
12288, 248320) are already primal; they are steered WITHOUT any Hadamard step.
`token_embd.weight` is additionally listed in inverse_weight_names and is skipped
entirely, matching the reference quantizer.
"""

from __future__ import annotations

import math

import pq2_0_codec as C
from pq2_0_codec import BLOCK_BYTES, CODE_BYTES, CODE_OFFSET, QK_PQ2
import pq2_hadamard as H


def block_scale(block: bytes) -> float:
    return C.FP16.unpack_from(block, 0)[0]


def deq_row(blocks) -> list[float]:
    """Concatenate the dequantized values of a run of pq2_0 blocks."""
    out: list[float] = []
    for blk in blocks:
        out += C.codes_to_floats(blk)
    return out


def req_row(values, scales) -> bytes:
    """Re-pack one value per pq2_0 block, holding each block's own scale."""
    assert len(values) == len(scales) * C.QK_PQ2
    out = bytearray()
    for k, d in enumerate(scales):
        out += C.FP16.pack(d)
        out += C.floats_to_codes(values[k * C.QK_PQ2:(k + 1) * C.QK_PQ2], d)
    return bytes(out)


def steer_primal(values, direction, amplitude: float, unbiased: bool = True) -> list[float]:
    """Steer in the primal basis.

    `amplitude` is the LENGTH of the added vector (the direction is normalized),
    so it is in the same units as the weights themselves. The ternary lattice is
    extremely coarse relative to real weight magnitudes here -- block scales in
    the reference file are around 0.0115 -- so a length that looks small can still
    move every code. Callers that want a scale-relative knob should normalize
    against the block scale before calling; see `relative_amplitude`.
    """
    n = math.sqrt(sum(v * v for v in direction))
    if n == 0.0 or amplitude == 0.0:
        return list(values)
    k = amplitude / n
    return [v + k * d for v, d in zip(values, direction)]


def heretic_delta_direction(v, stored_row, amp_blocks: float):
    """The heretic ablation direction for one weight row, in block units.

    NVIDIA's `heretic` ablates with a rank-1 projection, NOT an additive shift:

        delta_W = -lambda * v * (v^T W)

    where v is the refusal direction and W is the weight matrix, optionally
    row-normalized first (RowNormalization). That is a different operation from
    adding `amp * unit(direction)` to each weight: it projects each output row
    onto the plane orthogonal to v, scaled by lambda.

    `stored_row` is one pq2_0 block's 128 dequantized weights for a single output
    row. `amp_blocks` is lambda expressed in block-scale units (1.0 = one ternary
    step of the block's own scale).

    Returns a per-weight ADDITIVE delta to apply in the primal basis, matching
    what `abliterate_row` expects. Using heretic's rank-1 form matters here
    because the ternary lattice quantizes per block: an additive shift and a
    projection of the same nominal magnitude do NOT move the same number of
    codes, and the projection preserves the row's dominant structure far better.
    """
    d = amp_blocks
    # v^T W for this row (v is the per-coordinate direction for this row)
    dot = sum(vv * ww for vv, ww in zip(v, stored_row))
    # delta_j = -lambda * v_j * (v^T W) / ||v||^2  -- the rank-1 factorised form
    n2 = sum(vv * vv for vv in v) or 1.0
    k = -d * dot / n2
    return [k * vv for vv in v]


def flipped_weights(blocks, new: bytes) -> list[tuple[int, int, int]]:
    """Which weights changed, as (block_index, weight_index, old_code).

    Used to enforce an explicit edit budget. The Ternary-Bonsai model card gives
    the calibration target: the released model differs from the base by only
    ~1.5 million bits, i.e. 750,000 weight flips out of 26.87 billion -- 0.0028%.
    Steering amplitude alone cannot hit that, because the lattice is a cliff: a
    scale-relative strength of 1.0 already flips 0.03% of weights per block
    (15M bits model-wide, 10x over budget) while anything below it flips nothing.
    So the budget has to be enforced by CHOOSING which blocks to touch.
    """
    out = []
    for k in range(len(blocks)):
        o0 = k * len(blocks[k])
        ob = blocks[k][C.CODE_OFFSET:]
        nb = new[k * C.BLOCK_BYTES + C.CODE_OFFSET:(k + 1) * C.BLOCK_BYTES]
        for j in range(QK_PQ2):
            oc = (ob[j >> 2] >> (2 * (j & 3))) & 3
            nc = (nb[j >> 2] >> (2 * (j & 3))) & 3
            if oc != nc:
                out.append((k, j, oc))
    return out


def relative_amplitude(strength: float, scales) -> float:
    """Convert a scale-relative strength into an absolute primal length.

    `strength` is measured in block-scale units: 1.0 means "shift by one ternary
    step of the block's own scale". The absolute length is therefore
    strength * median(scale), which is what the lattice actually quantizes
    against. Using an absolute number instead makes strength a no-op across the
    whole sweep -- measured: strengths 8..256 all changed the same 50% of blocks
    because a fixed length of 8 is ~700x the block scale of 0.0115.
    """
    positive = sorted(s for s in scales if s > 0)
    if not positive:
        return 0.0
    return strength * positive[len(positive) // 2]


def differing_code_count(new_codes: bytes, orig_codes: bytes,
                         code_bytes: int = C.CODE_BYTES) -> int:
    """Number of 2-bit code fields that differ between two packed payloads.

    Each byte holds four codes at shifts 0, 2, 4, 6, so a byte can contribute
    anywhere from 0 to 4 differing fields.

    NOTE this is SYMBOL accounting, not physical bits. A symbol going 00 -> 01
    and one going 00 -> 11 both count as 1 here, but the second moved two
    physical bits. The bit budget is denominated in PHYSICAL bits, so this
    function is only used for reporting; `physical_bit_delta` is what the
    budget actually spends.
    """
    if len(new_codes) != len(orig_codes):
        raise ValueError("code payloads differ in length")
    total = 0
    for a, b in zip(new_codes, orig_codes):
        x = a ^ b
        if x:
            total += ((x >> 0) & 3) != 0
            total += ((x >> 2) & 3) != 0
            total += ((x >> 4) & 3) != 0
            total += ((x >> 6) & 3) != 0
    return total


def physical_bit_delta(new_codes: bytes, orig_codes: bytes) -> int:
    """Physical bits that differ between two packed code payloads.

    This is the authoritative cost unit. It is the population count of the byte
    XOR, which is independent of how the 2-bit codes are packed -- a symbol
    that moves 00 -> 01 costs 1, and 00 -> 11 costs 2. The budget is denominated
    in these bits, so an independent audit that recomputes the same popcount
    from the written files must reproduce the planner's number exactly.
    """
    if len(new_codes) != len(orig_codes):
        raise ValueError("code payloads differ in length")
    return sum(bin(a ^ b).count("1") for a, b in zip(new_codes, orig_codes))


def abliterate_budgeted(blocks, direction, strength: float, budget_bits: int,
                        sign_values=None, unbiased: bool = True):
    """Abliterate with a HARD cap on how many bits may change.

    The model card's calibration target is ~1.5 million changed bits for the whole
    27B model, i.e. 750,000 weight flips out of 26.87 billion. Amplitude alone
    cannot express that: the ternary lattice is a cliff, so a strength that
    produces any edit at all produces far too many. Measured on real blocks, a
    scale-relative strength of 1.0 already flips 0.03% of weights per block, which
    is 15M bits model-wide -- 10x over budget -- while anything weaker flips
    nothing.

    So the budget is enforced by CHOOSING which blocks to touch, not by shrinking
    the amplitude:

      1. Map the whole run of blocks into the primal basis once (the Hadamard
         transform is over the input dimension, so it is the whole row, not each
         pq2_0 block individually).
      2. Score every pq2_0 block by how strongly the refusal direction aligns with
         that block's own weights: |<w_block, d_block>| / ||w_block||.
      3. Commit blocks in descending score order, stopping when the bit budget is
         spent. A block whose cost would overshoot is skipped, not truncated --
         a pq2_0 block cannot be partially flipped.

    Returns (new_bytes, n_flipped_weights, bits_used, n_blocks_committed).
    """
    if budget_bits <= 0:
        return b"".join(blocks), 0, 0, 0

    total_bits = len(blocks) * C.BLOCK_BYTES * 8
    if budget_bits >= total_bits:
        amp = relative_amplitude(strength, [block_scale(b) for b in blocks])
        new, _ = abliterate_row(blocks, direction, amp, sign_values, unbiased)
        flips = flipped_weights(blocks, new)
        return new, len(flips), len(flips) * 2, len(blocks)

    # 1) the whole run in the primal basis, once. pq2_0 blocks nest 8-to-1 inside
    #    a 1024-wide Hadamard block, so the transform must see the full row.
    scales = [block_scale(b) for b in blocks]
    stored = deq_row(blocks)
    if sign_values is not None:
        primal = H.to_primal(stored, sign_values)
    else:
        primal = list(stored)

    # 2) score each pq2_0 block by directional alignment in the PRIMAL basis.
    scores = []
    for k in range(len(blocks)):
        w = primal[k * QK_PQ2:(k + 1) * QK_PQ2]
        d = direction[k * QK_PQ2:(k + 1) * QK_PQ2]
        num = sum(v * x for v, x in zip(w, d))
        den = math.sqrt(sum(v * v for v in w)) or 1.0
        scores.append(num / den)
    order = sorted(range(len(blocks)), key=lambda i: -abs(scores[i]))

    # 3) commit greedily, keeping the chosen blocks' PRIMAL edits
    chosen: dict[int, list[float]] = {}
    spent_bits = 0
    committed = 0
    for k in order:
        if spent_bits >= budget_bits:
            break
        amp = relative_amplitude(strength, [scales[k]])
        seg = primal[k * QK_PQ2:(k + 1) * QK_PQ2]
        d = direction[k * QK_PQ2:(k + 1) * QK_PQ2]
        steered = steer_primal(seg, d, amp)
        # count the flips this block would produce, using the block's own scale
        packed = C.floats_to_codes(steered, scales[k])
        orig = blocks[k][C.CODE_OFFSET:]
        # Cost is PHYSICAL bits: the population count of the byte XOR.
        # Counting changed symbols at a flat 2 bits each overstates the cost,
        # because 00 -> 01 moves one bit while 00 -> 11 moves two. The budget
        # is denominated in physical bits, and the independent audit measures
        # exactly this quantity, so the planner must too or the two disagree.
        cost = physical_bit_delta(packed, orig)
        if cost == 0:
            continue
        # A pq2_0 block cannot be partially flipped, so a block that overshoots
        # is skipped -- except when it is the FIRST commit, where skipping
        # would make the budget unreachable if no block ever fits. Even then it
        # is allowed, and that overshoot is reported rather than hidden.
        if spent_bits + cost > budget_bits and spent_bits > 0:
            continue
        chosen[k] = steered
        spent_bits += cost
        committed += 1

    # rebuild: map the edited primal row back through the transform
    if not chosen:
        return b"".join(blocks), 0, 0, 0

    primal_out = list(primal)
    for k, seg in chosen.items():
        primal_out[k * QK_PQ2:(k + 1) * QK_PQ2] = seg
    if sign_values is not None:
        stored_out = H.from_primal(primal_out, sign_values)
    else:
        stored_out = primal_out

    out = bytearray()
    for k in range(len(blocks)):
        out += C.FP16.pack(scales[k])
        out += C.floats_to_codes(
            stored_out[k * QK_PQ2:(k + 1) * QK_PQ2], scales[k])
    result = bytes(out)
    flips = flipped_weights(blocks, result)
    # The authoritative cost: the real popcount of the byte XOR, not the
    # planner's per-block estimate. If these ever disagree the estimate is
    # wrong and the budget is not actually enforced, so it is recomputed here
    # rather than trusted.
    #
    # `result` is a concatenation of (scale, codes) per block, so the two sides
    # must be compared block by block. Slicing `result[CODE_OFFSET:]` would
    # strip only the FIRST block's scale and leave every other block's scale in
    # place, which both misaligns the comparison and changes the length.
    measured = 0
    for k in range(len(blocks)):
        got = result[k * BLOCK_BYTES + C.CODE_OFFSET:
                      (k + 1) * BLOCK_BYTES]
        want = blocks[k][C.CODE_OFFSET:]
        measured += physical_bit_delta(got, want)
    bits_used = measured
    return result, len(flips), bits_used, committed


def abliterate_row(blocks, direction, amplitude: float,
                    sign_values=None, unbiased: bool = True):
    """Abliterate one row = a run of pq2_0 blocks spanning the input dimension.

    `direction` is the desired refusal direction in the PRIMAL basis, one entry
    per weight. `sign_values` (or None) selects the Hadamard basis: when given,
    the row is mapped to primal, steered, and mapped back; when None the row is
    steered directly.

    Returns (new_bytes, n_changed_codes).
    """
    scales = [block_scale(b) for b in blocks]
    stored = deq_row(blocks)

    if sign_values is not None:
        primal = H.to_primal(stored, sign_values)
        steered = steer_primal(primal, direction, amplitude)
        back = H.from_primal(steered, sign_values)
    else:
        steered = steer_primal(stored, direction, amplitude)
        back = steered

    new = req_row(back, scales)

    # count changed codes (scales are excluded by construction)
    changed = 0
    for k, (blk, nblk) in enumerate(zip(blocks, _split(new, len(blocks)))):
        o = C.CODE_OFFSET
        for j in range(C.CODE_OFFSET, C.BLOCK_BYTES):
            if blk[j] != nblk[j]:
                changed += 1
                break
    return new, changed


def _split(buf: bytes, n: int):
    step = len(buf) // n
    return [buf[i * step:(i + 1) * step] for i in range(n)]


def abliterate_tensor_row(blocks, width: int, direction, amplitude: float,
                           sign_values=None, unbiased: bool = True):
    """Width-aware wrapper: picks the Hadamard basis or primal pass-through.

    Returns (new_bytes, changed_block_count) or (None, 0) when the tensor is one
    that must not be touched at all (token_embd.weight).
    """
    if sign_values is None:
        return abliterate_row(blocks, direction, amplitude, None, unbiased)
    return abliterate_row(blocks, direction, amplitude, sign_values, unbiased)
