# doc/json

## What this folder is for

Bulk JSON and JSONL datasets.

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

## Moving files in

Use `git mv` when the source is tracked, plain `mv` when it is untracked, then
update `.gitignore` if the destination contents must be ignored.


## Size discipline

`chatgpt_memory_candidates.json` is ~37 MB and `q_lines.txt` ~242 KB. Large
datasets do not belong in git history — once written, a blob is permanent. Keep
them here (ignored), and record in the sibling `README.md` how to regenerate.
