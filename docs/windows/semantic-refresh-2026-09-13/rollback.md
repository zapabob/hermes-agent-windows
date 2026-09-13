# Rollback — windows-semantic-refresh-2026-09-13

## Scope

Verified slices may land on main (per COMPLETE_MAIN_DEPLOY). Prefer `git revert` of the slice commit. Preserve unrelated WIP (Watchdog scripts, readme contract tests).

## SR-003a rollback

Revert the commit that adds `hermes_state_shared.py`, SessionDB `_shared_owned`/`close` release path, Goals `_acquire_session_db`, gateway openers using `acquire`, and `tests/hermes_state/test_shared_session_db_native.py`. Keep `RecoverableHandleCache` (pre-existing).

## Config / DB / binary

- Isolated test HOME only under `%TEMP%`.
- No force push / protection bypass.

## Lease / process

- Prefer `watchdog_maintenance` lease expiry over PID-only kill.
- Do not treat raw Hermes.exe counts as app instance counts.
