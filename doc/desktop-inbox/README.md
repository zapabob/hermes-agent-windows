# doc/desktop-inbox/

Files relocated from `C:\Users\downl\Desktop` on 2026-10-04.

The Desktop is the operator's working surface, not a version-controlled location.
When scripts and data accumulate there they drift from the repository with no
detection — three different `memory_sync.py` copies existed as a result. This
inbox makes the drift visible and reviewable.

Contents are git-ignored; only `README.md`, `AGENTS.md` and `DIVERGENCE.md` are
tracked.

## Contents

| Folder | Holds | Count |
|--------|-------|-------|
| `scripts/` | `.py`, `.ps1`, `.bat`, `.js`, `.awk` | 21 |
| `data/` | `.json`, `.jsonl`, `.txt`, `.md`, `*.env.example` | 4 |

## What to do with these

1. **Product code** (something a test or entry module should import) -> promote to
   `scripts/`, `tools/`, or a plugin, and add a test.
2. **Operator scratch** -> move into the matching `doc/scripts/<class>/` folder.
3. **Generated data** -> move into `doc/json/` or `doc/logs/`.
4. **Duplicate of a repo file** -> read `DIVERGENCE.md`, then either reconcile it
   deliberately or delete it. Do not merge blind.
5. **Dead** -> delete it. Nothing here is irreplaceable; if it were, it would
   already be in git.

## Rules

1. **This is an inbox, not a home.** Everything here came from the Windows
   Desktop, where the operator works. Files are reviewed, classified into a real
   destination (`doc/scripts/**`, `doc/json/**`, `scripts/` for product code), and
   then this folder is emptied. Do not let it become a second scratch sink.
2. **Move, do not copy.** If a file is promoted into the repo, `git mv` it out.
   A duplicate left behind in both places is exactly how the three divergent
   `memory_sync.py` copies in `DIVERGENCE.md` came to exist.
3. **Read `DIVERGENCE.md` before promoting anything.** Several inbox scripts have
   a repo counterpart with different content. Never overwrite a repo copy with an
   inbox copy on the assumption that "Desktop is newer".
4. **No secrets.** `*.env.example` belongs here (it is a template); a real `.env`
   never does. Redact tokens, cookies and session dumps.
5. **Secrets guard:** `.gitignore` covers this folder's contents. Nothing in
   `desktop-inbox/` is tracked except these policy files.
