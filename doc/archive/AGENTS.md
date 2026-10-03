# doc/archive

## What this folder is for

Operator artifacts worth version-controlling.

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


## The one exception

Unlike its siblings, `doc/archive/` contents **are** committed. It exists for
artifacts that are finished and want to survive — exported datasets, sealed
verification reports, audit bundles. If you are unsure whether an artifact is
finished, it is not: use `doc/json/` or `doc/reports/` and let it regenerate.
