# Divergence ledger

Inbox scripts that have a **different** counterpart already in the repository.
Reconciling these by overwriting the repo copy would be a regression risk, so
each row must be resolved deliberately.

Recorded 2026-10-04.

| Inbox file | sha256[:12] | Repo counterpart | sha256[:12] | Verdict |
|---|---|---|---|---|
| `scripts/memory_sync.py` | `27516810310d` | `sync_memory.py` (root) | `9826d31ca171` | **Diverge.** Three copies exist: this, the root entry module, and `scripts/standalone/sync_memory.py`. All three differ. |
| `scripts/social_sync_cron.py` | `bfc6f5cb78f2` | `scripts/memory/sync_memory_cron.py` | `6b7e927c0f9f` | **Large divergence** (15,947 vs 2,564 bytes). The inbox copy is a much older, larger implementation. The repo copy is the current one. |
| `scripts/sync_check.py` | `82ac3f65cef8` | none tracked | — | Repo `git grep` finds the filename referenced, but no such tracked file. Investigate the reference before deleting. |

## Known related defect

Both `sync_memory.py` (root) and `scripts/standalone/sync_memory.py` compute:

```python
REPO_ROOT = Path(__file__).resolve().parents[2]
```

That is correct only for the `scripts/standalone/` copy (two levels deep). At the
repository root it resolves to `C:\Users\downl\Documents` — not the repo. The
inbox copy is also a root-level script, so it carries the same latent bug if it
is promoted as-is.

**Do not** fix this by editing a copy in the inbox. Decide first which copy is
canonical, then fix that one and delete the others. See also the residual-risk
note in `_docs/2026-10-04_root-surface-tidy-doc-classification_hakua.md`.
