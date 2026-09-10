# CodeGraph / Daybreak Blue implementation receipt

Captured 2026-09-06 17:13 Asia/Tokyo for the frozen upstream target `b51c055a12220f8c7c18660e8599365012e19532`.

The implementation branch was merged through PR #106. The resulting `origin/main` was `e2075ae9f9088eb63ccfae2d9927d9f5831cce90` at capture time. The isolated candidate worktree is clean; the operator's primary checkout was not reset, cleaned, or stashed.

## Current workstation result

Desktop is running as the packaged `Hermes.exe` with PID 20432. Its native top-level window is titled `Hermes`, visible, and responding. The Go Watchdog is running on 9920, the recovery marker is healthy, the maintenance fence is `NORMAL`, and the managed backend manifest points to one backend (PID 2892) on port 9119. The backend status endpoint, llama model endpoint on 8080, embedding health endpoint on 8082, and Watchdog health endpoint on 9920 each returned HTTP 200 after the canonical stack restart.

The immediate failure was a corrupted recovery-budget document containing NUL bytes. The Watchdog could not parse it, and Desktop had also been left with a hidden renderer window. The recovery writer now uses same-directory temporary storage, flush, close, and atomic rename; the regression test proves that an interrupted write cannot replace the live state with a partial JSON document.

## CodeGraph evidence

CodeGraph 1.6.0 was already initialized in the isolated worktree and was synchronized successfully. The final index reports 8,700 files, 187,260 nodes, and 598,932 edges using the built-in SQLite WAL backend. The final ownership queries resolve `writeRecoveryState` to `reserveRecovery`, `markRecoveryHealthy`, and its regression test. Desktop sandbox launch is resolved from `main.ts` to `decideWindowsSandboxLaunch`, and `wireWindowReveal` is the single reveal lifecycle helper.

The CodeGraph query for `navigator.credentials` and `PublicKeyCredential` returned no Hermes symbols. A narrow source audit likewise found no Hermes WebAuthn callsite. The observed Windows Hello prompt therefore remains attributed to the provider login surface (`accounts.google.com`) rather than an app-owned credential probe. A fresh clean-profile, non-enrolled native smoke with an explicit prompt counter is still `NOT_RUN`, so this receipt does not call that scenario a pass.

## Verification boundary

PR #106 required checks passed, and PR #107 required checks also passed, including full Python tests (31m15s), Windows native Desktop, Windows native Python, Windows watchdog Go, security, upstream API, downstream policy, e2e, and lint gates. The post-merge ordinary CI, Windows downstream release, Windows Workstation Tier-1, Docker, and Nix workflows all passed. The PR is ready for main integration.

Reboot/re-login and sleep/resume qualification were not run because they require an explicit workstation lifecycle action. They remain `NOT_RUN`, not `PASS`. The local recovery instance is currently running with `--no-sandbox` after a renderer startup failure; the marker is back to `ok`, but this is recorded as a residual operational risk rather than a source-level sandbox claim.

The required PC-wide prompt file `C:\Users\downl\_docs\prompts\CLAUDE-FABLE-5.md` was not present. Work continued under the stricter applicable system and repository rules.

The machine-readable record is [2026-09-06-codegraph-daybreak-receipt.json](2026-09-06-codegraph-daybreak-receipt.json).
