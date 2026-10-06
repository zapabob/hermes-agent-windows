# PQ2 reference helpers

These existing codec and projection helpers are retained here so the repository
tests can run from a clean checkout. They were previously local files under
`tmp/`. Their executable behavior is preserved.

`pq2_0_codec.py` handles PQ2_0 (GGML type 142). `pq2_lattice.py` is a separate
TQ2_0 reference (type 35). The types have different block geometry and must not
be substituted for one another. No live model is rewritten by the unit tests.
