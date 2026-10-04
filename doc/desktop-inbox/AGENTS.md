# doc/desktop-inbox/

Files relocated from the Windows Desktop.
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
