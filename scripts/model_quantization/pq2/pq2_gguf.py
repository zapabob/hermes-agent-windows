"""TQ2_0 ternary lattice: block codec + unbiased abliteration projection.

SCOPE: this is the git fork's TQ2_0 (ggml type 35), a REFERENCE codec.
It is NOT the pq2_0 codec (ggml type 142) that
Ternary-Bonsai-2-27B-Abliterated-PQ2_0.gguf actually uses. Do not point it at
that file. See _docs/2026-10-01_pq2_abliteration_GroundTruth.md.
"""


from __future__ import annotations

import mmap
import struct
from dataclasses import dataclass, field
from pathlib import Path

from pq2_lattice import CODE_BYTES, GGML_TYPE_TQ2_0, QK_K, abliterate_block, codes_to_floats, quantize_block

GGUF_MAGIC = b"GGUF"
FP16 = struct.Struct("<e")


class GGUFError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# pq2_0 (ggml type 142) — the type the Bonsai PQ2_0 file actually uses.
# Measured from the file: 17/64 bytes per element exactly. Block layout is NOT
# yet confirmed against the prismL build, so nothing here writes tensor data.
# ---------------------------------------------------------------------------
GGML_TYPE_PQ2_0 = 142
PQ2_0_BYTES_PER_ELEM = 17.0 / 64.0        # 0.265625, exact
PQ2_0_CANDIDATE_BLOCK = 64               # elems per block -> 17 bytes/block
PQ2_0_BYTES_PER_BLOCK = 17


def pq2_0_nbytes(n_elements: int) -> int:
    """Byte size of a pq2_0 tensor, from the measured 17/64 bytes-per-element."""
    if n_elements * 17 % 64:
        raise GGUFError(f"{n_elements} elements is not a whole number of pq2_0 bytes")
    return n_elements * 17 // 64


def is_pq2_0(t: TensorEntry) -> bool:
    return t.ggml_type == GGML_TYPE_PQ2_0


def hadamard_spec(f: "GGUFFile") -> dict:
    """The prism.hadamard.* transform spec, or {} when the file has none.

    PQ2_0 weights are stored in a normalized Sylvester Walsh-Hadamard basis
    (block 1024, last dimension) with an explicit +/-1 sign vector per row
    group. Editing codes in that basis is NOT the same as editing weights, so
    any abliteration must invert the transform first.
    """
    out = {}
    prefix = "prism.hadamard."
    for k, v in f.kv.items():
        if k.startswith(prefix):
            out[k[len(prefix):]] = v
    return out



@dataclass
class TensorEntry:
    name: str
    n_dims: int
    dims: tuple[int, ...]
    ggml_type: int
    offset: int          # relative to data region start
    n_elements: int = 0
    # Byte length of this tensor's data, derived from the NEXT tensor's offset.
    # This is authoritative: the ggml type alone does not determine the byte size
    # for every type in this file (F32 norms are 1-D, and the ternary types use
    # their own block geometry), so a computed nbytes can disagree with the file
    # layout. Offsets are ground truth; padding is absorbed into this length and
    # copied verbatim by the writer.
    size: int = 0

    @property
    def is_tq2_0(self) -> bool:
        return self.ggml_type == GGML_TYPE_TQ2_0

    @property
    def n_blocks(self) -> int:
        return self.n_elements // QK_K

    @property
    def nbytes(self) -> int:
        """Byte length of this tensor's data region.

        Prefers the offset-derived `size`, which matches the file exactly. Falls
        back to the TQ2_0 formula only for hand-built entries with no offsets.
        """
        return self.size if self.size else self.n_blocks * (CODE_BYTES + 2)


@dataclass
class GGUFFile:
    path: Path
    tensors: list[TensorEntry] = field(default_factory=list)
    kv: dict = field(default_factory=dict)
    _data_start: int = 0
    _alignment: int = 32
    _header_end: int = 0
    _header_bytes: bytes = b""
    _file_size: int = 0

    # -- header parsing ----------------------------------------------------
    @classmethod
    def open(cls, path) -> "GGUFFile":
        """Parse the header via mmap; tensor bytes are read one block at a time.

        The PQ2_0 27B file is 6.71 GiB, so slurping it with read_bytes() would
        pin that much RAM for the whole session. mmap keeps the header parse
        cheap and lets the OS page in only the blocks actually touched.
        """
        path = Path(path)
        self = cls(path=path)
        self._fh = path.open("rb")
        self._blob = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            self._parse_header()
        except Exception:
            self.close()
            raise
        return self

    def close(self) -> None:
        blob = getattr(self, "_blob", None)
        if blob is not None:
            blob.close()
            self._blob = None
        fh = getattr(self, "_fh", None)
        if fh is not None:
            fh.close()
            self._fh = None

    def __enter__(self) -> "GGUFFile":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def nbytes_total(self) -> int:
        # NB: mmap.size is a METHOD, not an attribute, so hasattr() is true but
        # the value is a bound method. Call it; fall back to len() for bytes.
        b = self._blob
        if isinstance(b, mmap.mmap):
            return b.size()
        return len(b)

    def _u32(self, off: int) -> tuple[int, int]:
        return struct.unpack_from("<I", self._blob, off)[0], off + 4

    def _u64(self, off: int) -> tuple[int, int]:
        return struct.unpack_from("<Q", self._blob, off)[0], off + 8

    def _string(self, off: int) -> tuple[str, int]:
        n, off = self._u64(off)
        s = self._blob[off:off + n].decode("utf-8", errors="replace")
        return s, off + n

    def _parse_header(self) -> None:
        b = self._blob
        if b[:4] != GGUF_MAGIC:
            raise GGUFError(f"not a GGUF file: {self.path} (magic={b[:4]!r})")
        # `size()` for an mmap, len() for the bytes of a header-only re-parse.
        # Both are callable through this shim so the header snapshot can be
        # re-parsed in isolation to prove it is complete.
        self._file_size = b.size() if hasattr(b, "size") else len(b)
        off = 4
        version, off = self._u32(off)
        if version not in (2, 3):
            raise GGUFError(f"unsupported GGUF version {version}")
        n_tensors, off = self._u64(off)
        n_kv, off = self._u64(off)

        # KV pairs: key(str) type(u32) value(type-dependent)
        for _ in range(n_kv):
            key, off = self._string(off)
            vtype, off = self._u32(off)
            val, off = self._read_value(vtype, off)
            self.kv[key] = val

        self._header_bytes = b[:off]
        for _ in range(n_tensors):
            name, off = self._string(off)
            n_dims, off = self._u32(off)
            dims = []
            for _ in range(n_dims):
                d, off = self._u64(off)
                dims.append(d)
            ggml_type, off = self._u32(off)
            toff, off = self._u64(off)
            n = 1
            for d in dims:
                n *= d
            self.tensors.append(
                TensorEntry(name, n_dims, tuple(dims), ggml_type, toff, n, 0)
            )

        # `_header_bytes` must cover the WHOLE tensor-info table. Slicing it
        # before the loop above left the last directory entries out of the
        # snapshot, so a writer that copies the header verbatim truncated the
        # tensor table while still producing the right total length.
        self._header_bytes = b[:off]
        # Data region begins at the header end, padded UP to the alignment
        # (gguf.cpp:753-757: GGML_PAD(tell(), alignment), only if n_tensors>0).
        # Missing general.alignment means GGUF_DEFAULT_ALIGNMENT = 32.
        self._alignment = int(self.kv.get("general.alignment") or 32)
        if n_tensors > 0 and self._alignment > 1:
            rem = off % self._alignment
            if rem:
                off += self._alignment - rem
        self._data_start = off
        self._header_end = off  # equals data start after padding

        # Derive each tensor's byte length from the NEXT tensor's offset. The
        # ggml type alone is not sufficient: F32 norm tensors here are 1-D, and
        # the ternary types carry their own block geometry, so a formula-based
        # nbytes disagrees with the real layout. Offsets are ground truth. The
        # last tensor runs to the end of the data region.
        #
        # Skipped when the buffer holds only the header (a header-completeness
        # re-parse), because there the data region length is not knowable from
        # this buffer and every derived size would come out negative.
        data_len = self._file_size - self._data_start
        if data_len > 0:
            for i, t in enumerate(self.tensors):
                end = self.tensors[i + 1].offset if i + 1 < len(self.tensors) else data_len
                t.size = end - t.offset
                if t.size < 0:
                    raise GGUFError(
                        f"tensor {t.name} has a negative size ({t.size}); "
                        f"offsets are not monotonic"
                    )

    def _read_value(self, vtype: int, off: int):
        """Read one KV value. Type IDs from ggml/include/gguf.h:53-68.

          0 UINT8  1 INT8   2 UINT16 3 INT16  4 UINT32 5 INT32
          6 FLOAT32 7 BOOL  8 STRING 9 ARRAY 10 UINT64 11 INT64 12 FLOAT64

        STRING/ARRAY are self-delimiting (u64 length prefix), everything else is
        a fixed-width little-endian scalar.
        """
        if vtype == 0:
            return struct.unpack_from("<B", self._blob, off)[0], off + 1
        if vtype == 1:
            return struct.unpack_from("<b", self._blob, off)[0], off + 1
        if vtype == 2:
            return struct.unpack_from("<H", self._blob, off)[0], off + 2
        if vtype == 3:
            return struct.unpack_from("<h", self._blob, off)[0], off + 2
        if vtype == 4:
            return struct.unpack_from("<I", self._blob, off)[0], off + 4
        if vtype == 5:
            return struct.unpack_from("<i", self._blob, off)[0], off + 4
        if vtype == 6:
            return struct.unpack_from("<f", self._blob, off)[0], off + 4
        if vtype == 7:
            return bool(struct.unpack_from("<B", self._blob, off)[0]), off + 1
        if vtype == 8:
            return self._string(off)
        if vtype == 9:  # ARRAY: elem_type(u32) THEN count(u64), per gguf.cpp:575-579
            elem_type, off = self._u32(off)
            n, off = self._u64(off)
            if n > self.nbytes_total:
                raise GGUFError(f"implausible array length {n} at offset {off}")
            out = []
            for _ in range(n):
                v, off = self._read_value(elem_type, off)
                out.append(v)
            return out, off
        if vtype == 10:
            return struct.unpack_from("<Q", self._blob, off)[0], off + 8
        if vtype == 11:
            return struct.unpack_from("<q", self._blob, off)[0], off + 8
        if vtype == 12:
            return struct.unpack_from("<d", self._blob, off)[0], off + 8
        raise GGUFError(f"unknown GGUF value type {vtype} at offset {off}")

    # -- tensor data -------------------------------------------------------
    def tensor_bytes(self, t: TensorEntry) -> bytes:
        start = self._data_start + t.offset
        return self._blob[start:start + t.nbytes]

    def block_at(self, t: TensorEntry, block_index: int) -> bytes:
        """One 66-byte TQ2_0 block, read lazily from the mapping."""
        if not t.is_tq2_0:
            raise GGUFError(f"{t.name} is not TQ2_0 (type {t.ggml_type})")
        if not 0 <= block_index < t.n_blocks:
            raise IndexError(f"block {block_index} out of range for {t.name} ({t.n_blocks})")
        start = self._data_start + t.offset + block_index * (CODE_BYTES + 2)
        return self._blob[start:start + CODE_BYTES + 2]

    def iter_tq2_0(self):
        """Yield (tensor, block_index, qs, d) for every TQ2_0 block in the file."""
        for t in self.tensors:
            if not t.is_tq2_0:
                continue
            for bi in range(t.n_blocks):
                blk = self.block_at(t, bi)
                qs = blk[:CODE_BYTES]
                d = FP16.unpack_from(blk, CODE_BYTES)[0]
                yield t, bi, qs, d

    def summary(self) -> dict:
        tq2 = [t for t in self.tensors if t.is_tq2_0]
        return {
            "path": str(self.path),
            "file_bytes": len(self._blob),
            "n_tensors": len(self.tensors),
            "n_tq2_0_tensors": len(tq2),
            "n_tq2_0_blocks": sum(t.n_blocks for t in tq2),
            "n_tq2_0_elements": sum(t.n_elements for t in tq2),
            "types": sorted({t.ggml_type for t in self.tensors}),
            "kv_keys": len(self.kv),
            "alignment": self._alignment,
            "data_start": self._data_start,
        }

    def find(self, needle: str) -> list[TensorEntry]:
        return [t for t in self.tensors if needle in t.name]
