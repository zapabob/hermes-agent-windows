# skill-vault rules

Normative rules for this class folder. Written before content lands (§17.3 SOP).

## Purpose

Inactive (non-loading) skills and plugins live here in a browsable, instantly
readable form so the agent harness can be pointed at `INDEX.md` and pull an
item back into service without hunting through dot-directories.

## Rules for agents

1. **Read `INDEX.md` first.** It is the generated manifest. If it is stale,
   regenerate with `doc/scripts/skill-vault/skill-vault.ps1 index` instead of
   editing it by hand.
2. **Move semantics for `store`/`pull`.** A stored item exists in exactly one
   of: active dir (`~/.hermes/skills|plugins`), this vault, or the Curator's
   `skills/.archive`. Never duplicate an item across two of those buckets
   except the deliberate `import-archive` copy path.
3. **`import-archive` is copy-only.** The Curator owns `~/.hermes/skills/.archive`
   and its ledgers (`.usage.json`, `.curator_ledger.jsonl`). Never move or
   delete items from `.archive`; the vault import must not disturb them.
4. **No overwrite.** `store` and `pull` abort when the destination path already
   exists. Resolve the conflict explicitly; never silently merge skill dirs.
5. **Origin is recorded.** Every move appends to the vault ledger (JSON); a
   `pull` restores the item to its recorded origin home/profile. Hand-moving
   vault items breaks that contract — always use the tool.
6. **Cache-safety.** Active skill/plugin changes only take effect on the next
   agent session. Do not vault or pull mid-conversation as a "hot reload".
7. **Never commit contents.** `skills/`, `plugins/`, `INDEX.md`, and the ledger
   stay git-ignored (machine-local). Only this AGENTS.md and README.md are
   tracked.
8. **No secrets.** Plugin/skill payloads sometimes carry tokens or `.env`
   fragments; vaulting is for prompt/skill text and tooling, not credential
   stores. Strip or refuse such material.
9. **Path rule.** All Hermes-state paths the tool touches resolve from the
   active `HERMES_HOME` (or `~/.hermes` default) — never hardcoded drive
   letters — and honor `-Profile` for profile-scoped state (§ Profiles policy).
