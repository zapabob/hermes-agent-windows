# Divergence ledger (RESOLVED 2026-10-04)

Inbox scripts that have a **different** counterpart already in the repository.
Reconciling these by overwriting the repo copy would be a regression risk, so
each row must be resolved deliberately.

Recorded 2026-10-04. **All three rows are now resolved** — see Resolution below.

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


## Resolution (2026-10-04)

### `memory_sync.py` — resolved: one canonical implementation

| Path | Role after resolution |
|---|---|
| `scripts/standalone/sync_memory.py` | **CANONICAL** — the only implementation |
| `sync_memory.py` (repo root) | Compatibility shim; re-exports the canonical module, zero logic |
| `doc/desktop-inbox/superseded/memory_sync.legacy-generic.py` | Superseded pre-CLI generation, retained for reference, never executed |

Evidence for the choice:

- The root copy and the standalone copy differed by exactly **one** real change: the
  root copy wrapped `main()` in `try/except` returning `{"success": false, "error": ...}`
  as JSON. That change was **ported into the canonical copy**, because the cron wrapper
  `scripts/memory/sync_memory_cron.py` parses stdout with `json.loads` and would
  mislabel a traceback as `invalid JSON from sync_memory.py`.
- `parents[2]` is only correct for the `scripts/standalone/` copy. At the repo root it
  resolves to `C:\Users\downl\Documents`. This was verified to be a **latent defect,
  not a live break**: the package is pip-installed editable
  (`__editable__.hermes_agent-0.21.3.pth`), so the repository is on `sys.path`
  regardless of what the script computes. Both copies run correctly from a foreign
  cwd and under system Python 3.12. Deciding on `scripts/standalone/` removes the
  discrepancy by construction rather than by luck.
- The inbox copy was a different generation entirely: no argparse CLI (0
  `add_argument` calls), four hardcoded `C:\Users\downl\...` paths, and no import of
  the Hermes modules. It could not satisfy the wrapper's CLI-surface detection. Its
  `SECRET_MARKERS` list is **weaker** than the canonical pipeline, which applies
  `redact_sensitive_text()` with three regex families plus a 32-char high-entropy
  pattern, so nothing was lost by retiring it.

Shim constraints (both enforced by `tests/scripts/test_sync_memory.py`):

1. Importing the shim must have **no side effects** — it loads the canonical module,
   it does not execute it. A first attempt used `exec(compile(...), {"__name__":
   "__main__"})`, which ran the argparse CLI at import time and made pytest fail with
   `INTERNALERROR`.
2. The shim re-exports **every** module-level name, private ones included. Tests
   monkeypatch `sync_memory._export_obsidian`; re-exporting only the public surface
   raised `AttributeError`. Note that this patch is currently vestigial (the tests pass
   `export_obsidian=False`), so it is future-proofing rather than a live fix.

### `social_sync_cron.py` — resolved: repo copy is authoritative

The inbox copy (15,947 bytes) is an older, larger implementation; the repo copy
`scripts/memory/sync_memory_cron.py` (2,564 bytes) is current. The deployed wrapper at
`~/.hermes/scripts/sync_memory_cron.py` carries `_resolve_sync_script()` and the
`--max-x-events 0` argument, neither of which is in the repo copy — **the deployed
wrapper is ahead of the repository**. That gap should be closed by syncing the
deployed copy back into `scripts/memory/`, per
`cron-runtime-reliability` -> `references/sync-allowlist-workflow.md`.

### `sync_check.py` — retained in the inbox

No tracked counterpart exists. The name is referenced by the repo, so it was kept for
inspection rather than deleted.
