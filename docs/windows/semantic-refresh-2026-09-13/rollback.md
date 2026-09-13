# Rollback — windows-semantic-refresh-2026-09-13

## Scope

Local feature branch only. No push/tag/release performed by this campaign.

## Code rollback

```powershell
cd "C:\Users\downl\Documents\New project\hermes-agent\.worktrees\semantic-refresh-d1"
git log --oneline -5
# Revert a single slice commit (example):
git revert --no-edit <slice-commit-sha>
```

Do **not** `git reset --hard` on the dirty main checkout. Main WIP
(`scripts/windows/watchdog-go/*`) is unrelated and must stay preserved.

## Config / DB / binary

- No production `HERMES_HOME`, secrets, or live DBs were modified.
- Test HOME used under `%TEMP%\hermes-sr-test-*` only — safe to delete.
- No installer / Desktop package was rebuilt for production.

## Lease / process

- No production Watchdog / Gateway / Desktop / llama processes were stopped.
- If a future slice touches maintenance fences, restore via existing
  `watchdog_maintenance` lease expiry rather than PID-only kill.
