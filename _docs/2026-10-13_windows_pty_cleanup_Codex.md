# Windows PTY process-tree cleanup

`ProcessRegistry.kill_process()` now routes Windows PTY termination through the existing start-time-checked `_terminate_host_pid()` helper. If the PTY PID is gone or its recorded start time no longer matches, the session is finalized as already exited without calling the PTY handle or a bare PID signal.

The native Windows regression launches a real local ConPTY shell with a nonce-bound parent and child under a Japanese, spaced temporary path, plus an unrelated held sentinel. The test verifies the child relationship and process creation times, then requires the parent and child to exit after kill while the sentinel remains alive until fixture teardown. A separate control verifies a stale PID is not signaled through the PTY handle, tree helper, or `os.kill`.

The bounded H-drive acceptance and raw logs are recorded in `H:/Codex-v0216-archive/V0217_PRODUCTION_PTY_CLOSEOUT_20261013.md`. Ruff passed for the two changed Python files, and the CodeGraph index was synced once after those source and test edits.

The initial R2 review identified three best-effort behaviors in the reused helper: missing start-time data degraded ownership checks to PID liveness; Windows `taskkill` errors fell back to `os.kill` while a nonzero exit code was unchecked; and a second-check mismatch had no returned disposition, so the caller could still record a killed result without signaling. The R3 repair below addresses these behaviors only for Windows PTY termination; legacy detached and Popen callers retain their prior helper contract. No atomic process-handle ownership primitive is added.

## Review repair: strict Windows PTY outcome

The follow-up keeps the legacy best-effort behavior for detached and Popen callers, while the Windows PTY branch now uses `_host_pid_identity_state()` and opts into an explicit result from `_terminate_host_pid()`. A missing captured start time or an unreadable live start time returns an ownership error and leaves the session in the running registry. A provably dead or reused PID is finalized as already exited. The strict path rechecks identity before `taskkill`, accepts only exit code 0 as confirmed, and returns a retryable error on nonzero exit, timeout, or OS error without a PID-only `os.kill` fallback. The check is not atomic with process creation or termination; the native test verifies observed tree termination and sentinel survival.

The sanitized native Windows R3 cohort passed 13 selected cases, covering the real PTY parent/child/sentinel scenario, unknown and changed identity, taskkill failures, existing stale-PID protection, detached-session compatibility, and PTY input controls. Ruff and `git diff --check` passed. The additive H-drive evidence is `H:/Codex-v0216-archive/V0217_PRODUCTION_PTY_CLOSEOUT_R3_20261013.md`; the prior closeout and review artifacts remain unchanged.
