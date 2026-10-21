# skill-vault

Readably vaulted **inactive skills and plugins** for the Hermes agent harness on
this workstation.

When a skill or plugin is deactivated (uninstalled, Curator-archived, or moved
out of `~/.hermes/skills` / `~/.hermes/plugins`), it does not disappear into
dot-folders. It is kept here, fully browsable, so any AI agent session can read
it out immediately (`INDEX.md` is the entry point) and, when needed again, pull
it back into the active directories with one command.

## What belongs here

| Path | Holds | Tracked? |
|------|-------|----------|
| `skills/<name>/` | Vaulted inactive skill directories (moved or snapshot-copied) | No |
| `plugins/<name>/` | Vaulted inactive plugin directories | No |
| `INDEX.md` | Generated manifest of vault contents + active-side counts | No |

Secrets-bearing material (tokens, cookies, `.env`-style payloads) must not be
added even though this tree stays local.

## Workflow (the loop)

1. **Deactivate + vault** — `doc/scripts/skill-vault/skill-vault.ps1 store -Name <x>`
   moves the directory out of the active location into this vault.
2. **Read / use** — Agents read skills directly from this vault, or pull one
   back: `... pull -Name <x>` restores it to its origin (active skills dir,
   profile-aware, preserving Curator archive copies).
3. **Store again** — When no longer needed, run `store -Name <x>` once more.

Activation/deactivation takes effect on the **next agent session** — never
mid-conversation (prompt-cache safety, AGENTS.md core policy).

## Tool

`doc/scripts/skill-vault/skill-vault.ps1` — `usage`, `list`, `index`, `store`,
`pull`, `import-archive`. `import-archive` snapshot-copies the Curator's
`skills/.archive` into this vault without touching the archive itself.

## Reading order

1. `AGENTS.md` (this class's rules) — before landing anything here.
2. `INDEX.md` — what is currently vaulted.
3. Tool help: `powershell -File doc/scripts/skill-vault/skill-vault.ps1 usage`
