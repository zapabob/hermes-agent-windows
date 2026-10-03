# doc/scripts/semantic-scan/

Semantic-graph and contradiction scan helpers that used to sit in `tools/`.

These were **not** registered tools (`registry.register` absent in every one), so
they never appeared in any tool schema and nothing could import them as product
code. They are operator diagnostics: run them, read the output, move on.

Contents are git-ignored; only `README.md` and `AGENTS.md` are tracked.

## Scripts

| Script | Purpose |
|--------|---------|
| `scan_lib.py` | Shared helpers for the scan suite |
| `scan_stage_a.py` | Stage A pass |
| `scan_stage_b.py` | Stage B pass |
| `scan_duplicates.py` | Duplicate-edge detection |
| `scan_neardupe.py` | Near-duplicate detection |
| `scan_chain_tips.py` | Dangling chain-tip detection |
| `scan_chains_detail.py` | Per-chain detail dump |
| `scan_verify_mislink.py` | Mislinked-node verification |
| `scan_final_verify.py` | Final verification pass |
| `contradiction_scan.py` | Ebbinghaus contradiction scan |
| `contradiction_inspect.py` | Contradiction result inspector |

## Promotion path

If any of these ever needs to become a real capability, it does **not** move back
to `tools/` by hand — it gets a `tools/registry.py` `registry.register(...)`
entry, a two-file registration (see `AGENTS.md` §7), and a test under
`tests/`. Until then it stays here.

## Rules

1. **Nothing here is product surface.** No file in `doc/` may be imported by a
   test, an entry module, or packaging. If code must be importable, it belongs in
   `scripts/`, `tools/`, or the plugin it serves.
2. **No secrets.** `.env`, tokens, cookies, session dumps, and raw API
   responses with credentials never land here. Redact before writing.
3. **Read before you write.** Every class folder has a `README.md` describing
   what belongs in it. Check it first; if the folder does not fit, create a new
   class folder with its own README rather than dumping into the nearest one.
4. **Prefer regeneration over curation.** Most of this is reproducible from a
   script. Note the producing command in a sibling `README.md` line when known,
   so the file can be rebuilt rather than preserved forever.
5. **Leave the folder, never the root.** Move, do not copy. The root surface is
   governed by `AGENTS.md` §17 and a stray root file undoes that work.
