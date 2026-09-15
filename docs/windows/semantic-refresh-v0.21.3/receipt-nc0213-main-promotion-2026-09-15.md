# Receipt — NC-0213 promotion to main (operator-approved)

| Field | Value |
|---|---|
| Campaign | windows-native-carry-v0.21.3 → downstream main |
| Gate tested SHA | `7b5592ef32372690a604e9d0a464ec760c9aeea7` |
| Branch tip / C (local) | `d73b9586eac25e87bd182bc309d81e985d023517` |
| Docs-only proof `7b5592ef32..d73b9586ea` | **PASS** — only `docs/windows/semantic-refresh-v0.21.3/receipt-nc0213d-promotion-gate-2026-09-15.md` (+48); no runtime/source files |
| Clean integration worktree | `.worktrees/integrate-v0213-main` FF-merge from `origin/main` |
| Primary checkout FF | `af685eba69` → `d73b9586ea` (untracked WIP preserved; no reset --hard) |
| `allow_upstream_sync` | **false** (unchanged) |
| Pre-deploy focused pytest | **64 passed, 1 skipped** |
| Pre-deploy Go watchdog | **ok** |
| Pre-deploy policy/carry | **POLICY_OK** |

## Status gates

| Gate | Status | Note |
|---|---|---|
| MAIN_INTEGRATED | **PASS** (local) | Exact C on primary `main` + integrate worktree |
| REMOTE_MAIN_PUSHED | **PASS** | `af685eba69..d73b9586ea  HEAD -> main`; `origin/main` == C |
| LOCAL_RUNTIME_DEPLOYED | **IN_PROGRESS** | Rebuild/restart from confirmed remote C |
| POST_DEPLOY_HEALTH | **PENDING** | After stack restart |
| CI_CD_FINAL_MAIN | **PENDING** | Watch check-runs on C |

## Push evidence

- Clean integrate worktree push: `git push origin HEAD:main` exit 0
- Verified: `git rev-parse origin/main` == `d73b9586eac25e87bd182bc309d81e985d023517`

## Forbidden actions not used

- force push, reset --hard WIP wipe, bulk upstream merge/rebase, `allow_upstream_sync:true`, committing untracked scratch, bypassing branch protection / UAC
