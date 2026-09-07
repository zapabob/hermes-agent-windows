# Upstream Windows Semantic Carry — 2026-09-08

## Mission

Selectively carry **observable Hermes semantics** from `NousResearch/hermes-agent`
into `zapabob/hermes-agent-windows` for native Windows reliability.

**Not** source-tree parity. **Not** merge/rebase of `upstream/main`.
**Not** mechanical cherry-pick of PR #102117 module layout.

```text
Upstream determines Hermes behavior.
Downstream determines how that behavior is made reliable on native Windows.
```

## Authoritative baselines (reconfirmed 2026-09-08)

| Role | Value |
|------|--------|
| Downstream start (`origin/main`) | `37aade8afb6ff944dfbe1b6ee32485b1b1c71e3e` |
| Implementation branch | `feat/upstream-windows-semantic-carry-2026-09-08` @ same SHA |
| Frozen upstream (`.codex/UPSTREAM_SNAPSHOT.json`) | `b51c055a12220f8c7c18660e8599365012e19532` — **unchanged** |
| Design-time upstream main (spec) | `42da1f2cf444028e1da708760394040f493f2e43` |
| Live `upstream/main` at carry start | `a7198a8855ad98681114ff5138eb01fe132a62e7` |
| Historical merge base | `1fe0f2f3ac9748ce799272eb93bee2937b5ab802` |

`UPSTREAM_SNAPSHOT.json` is historical provenance only. This campaign does **not**
advance the frozen release baseline.

## CodeGraph navigation (required)

Local CodeGraph CLI:

```text
.tools/codegraph-cli/node_modules/.bin/codegraph.cmd
```

Index: `.codegraph/` (machine-local; do not commit).

Observed queries used to classify candidates:

| Query / explore | Finding |
|-----------------|--------|
| `query WinPtyBridge` | `write(self, data: bytes) -> None` @ `hermes_cli/win_pty_bridge.py:150` — **sync** |
| `query PtySession` | no `_attach_generation`, no `async write(ws, data)` |
| `query HERMES_PTY_HOST` | **no results** |
| `query _fleet_probe_expected_runtimes` | `hermes_cli/update_cmd.py:10521`; plan still keys on any `runtimes` |
| `query watchdog_maintenance` | lease owner present (`WatchdogMaintenanceLease`) |
| `query try_activate_fallback` | recursive candidate walk still present |
| `impact CredentialPool` | pool owns refresh/cooldown; CLI missing `priority`/`refresh` |
| `query openBrowserTab` | Desktop Browser pane owner intact |

CodeGraph is prepared navigation context only — not verification evidence.

---

## Classification legend

| Tag | Meaning |
|-----|---------|
| **PORT** | Downstream lacks equivalent observable contract; introduce upstream semantics with minimum local surface |
| **COMPOSE** | Downstream already owns Windows authority; realize upstream observable behavior through that owner |
| **ALREADY_EQUIVALENT** | Different code, same contract — do not churn |
| **SKIP** | Upstream-internal refactor, Linux/macOS-only, or would weaken a stronger downstream invariant |

---

## Required candidate commits

### 1. `a99340c247` — ConPTY / PTY input backpressure

| | |
|--|--|
| **Class** | **PORT** |
| **Upstream semantics** | `async def write(data, *, timeout=10.0) -> bool` on Win+POSIX bridges; timeout → terminate ConPTY + reap worker; `CancelledError` → grace then terminate only if write never lands; socket lifetime ≠ PTY lifetime |
| **Downstream now** | Sync `WinPtyBridge.write` / `PtyBridge.write`; `web_server` calls `session.bridge.write(raw)` on event loop |
| **CodeGraph** | `WinPtyBridge.write` signature confirms sync contract |
| **Owners** | `hermes_cli/win_pty_bridge.py`, `hermes_cli/pty_bridge.py`, `hermes_cli/pty_session.py`, `hermes_cli/web_server.py` |
| **Tests** | extend `tests/hermes_cli/test_win_pty_bridge.py`, `test_pty_bridge.py`, `tests/test_pty_session.py`, keepalive WS tests |
| **Do not copy** | Upstream `PLUGIN-COMPAT` / COMPAT_MANIFEST re-export block |

### 2. PtySession ownership generation (same commit family)

| | |
|--|--|
| **Class** | **PORT** |
| **Upstream semantics** | `_attach_generation`, `_write_lock`, `async write(ws, data)`, attach returns bool, force_redraw via `await self.write`, `close()` sets `alive=False` first; superseded socket late failure must not kill replacement |
| **Downstream now** | attach/detach only; sync force redraw; close does not clear `alive` first |
| **Stalled input** | **PORT** — close **only** the affected terminal WebSocket (code `1013`, reason `PTY input stalled`); never kill Dashboard/gateway/Desktop/watchdog |

### 3. `04fd0172cd` — Dashboard PTY host + Alt-Tab focus

| | |
|--|--|
| **Class** | **PORT** |
| **Upstream semantics** | Spawn env `HERMES_PTY_HOST=dashboard` on Win+POSIX; Ink skips focus-in erase+repaint under dashboard host; `shouldRestoreTerminalFocus` restores xterm only when `activeElement` is null/body/inside terminal host |
| **Downstream now** | CodeGraph: `HERMES_PTY_HOST` absent; no `web/src/lib/pty-focus.ts` |
| **Compose note** | Preserve Chrome/Edge → `hermes://open/browser` focus ownership; do not steal sidebar/composer focus |
| **Owners** | `hermes_cli/pty_bridge.py`, `hermes_cli/win_pty_bridge.py`, `ui-tui/.../hermes-ink`, `web/src/lib/pty-focus.ts` (add), ChatPage focus wiring |

### 4. `f17f18cd11` — Windows staged Desktop promotion locks

| | |
|--|--|
| **Class** | **COMPOSE** |
| **Upstream semantics** | Before live→previous rename: re-stop install-scoped Desktop; after force-kill, second bounded `wait_procs` for handle release; fail closed / rollback on unresolved lock |
| **Downstream owner** | `hermes_cli/main.py::_stop_desktop_processes_locking_build` (+ watchdog maintenance lease in update path). No `main_desktop.py` — do **not** invent upstream module layout |
| **Gap** | Pre-pack stop exists; missing (a) re-quiesce immediately before any live release rename/promotion after long packaging, (b) second wait after escalate kill |
| **Critical** | No PID-only `taskkill`; install-scoped exe/release root only; unrelated Hermes installs untouched; unknown lock → promotion failure |

### 5. `b8e3c5c700` — fleet-probe runtime-kind

| | |
|--|--|
| **Class** | **PORT** (one-line semantic fix in existing owner) |
| **Upstream semantics** | `pre_update_plan.runtimes` expectation requires `any(kind == "gateway")`; dashboard/serve-only plans must **not** expect fleet rows; Windows resume token still excluded |
| **Downstream now** | `update_cmd.py` still: `if pre_update_plan is not None and pre_update_plan.runtimes: return True` |
| **Owner** | `hermes_cli/update_cmd.py::_fleet_probe_expected_runtimes` (re-exported via `hermes_cli.main`) |
| **Tests** | `tests/hermes_cli/test_update_fleet_check_fail_closed.py`, `test_update_fleet_probe_resume_token.py` |

### 6. `fc70d05bb1` — fallback cooldown ownership

| | |
|--|--|
| **Class** | **PORT** |
| **Upstream semantics** | Arm primary cooldown once; walk candidates in a single loop; skip/quarantine without recursively re-arming |
| **Downstream now** | `try_activate_fallback` still `return agent._try_activate_fallback(reason)` on skip paths (recursive side effects) |
| **Owner** | `agent/chat_completion_helpers.py` — preserve Hypura / local llama / custom OpenAI / OpenRouter / Codex / Anthropic / Nous |

### 7. `32a59f3bf7` + `1a4bb74a40` + `53221df05f` — pooled OAuth / priority / reset CLI

| | |
|--|--|
| **Class** | **PORT** (CLI surface) + **ALREADY_EQUIVALENT** (pool refresh/cooldown internals) |
| **Upstream semantics** | `hermes auth list` shows id+priority; `priority` / `refresh` / targeted `reset`; multi-entry refresh without target → fail closed; refresh clears **that** credential's cooldown only |
| **Downstream now** | `hermes_cli/subcommands/auth.py`: add/list/remove/reset/status/logout/spotify — **no** `priority`/`refresh`; `CredentialPool._refresh_entry` / `try_refresh_*` already exist |
| **Rule** | Do **not** create a second credential authority |

### 8. `f9d05081d8` + `478d772f2c` — remote artifact provenance

| | |
|--|--|
| **Class** | **COMPOSE** / verify → tighten if gap |
| **Upstream semantics** | Remote `~/` `./` `../` stay gateway-owned; Desktop downloads via authenticated originating connection/session/profile bridge — never expand on Windows client cwd |
| **Downstream now** | `artifact-utils.ts` / `media.ts` / gateway file download paths exist; confirm remote relative paths never hit `C:\Users\...` |
| **Protect** | Do not confuse with Browser URL routing |

### 9. `026e3e84ea` — fail-closed Desktop profile/session targets

| | |
|--|--|
| **Class** | **PORT** if missing; else **ALREADY_EQUIVALENT** after characterisation |
| **Upstream semantics** | Explicit missing/unreadable profile → ERROR (never launch/default profile); explicit stale session → not found + zero config mutation |
| **Downstream owners** | `tui_gateway/server.py`, Desktop profile routing / session actions |
| **Tests** | add/extend fail-closed targeting tests mirroring upstream contract |

### 10. `0b3391322c` — provider setup profile ownership

| | |
|--|--|
| **Class** | **COMPOSE** / verify |
| **Upstream semantics** | Desktop provider setup bound to selected profile; cancel/invalidate late results on close/reopen |
| **Downstream** | Profile-scoped settings/onboarding already present; verify Applies-to remount + request binding without weakening secret scope |

### Post-snapshot security follow-ups (in `b51c055..upstream/main`)

| Commit | Class | Notes |
|--------|-------|-------|
| `bbbccd3935` failed probe ≠ configured fallback | **PORT** if gap | capability probe boundary |
| `7d44fe9c74` mint credentials at probe only | **PORT** if gap | no callable/token in logs/repr |
| `a745101e5f` Gemini `google` alias → GeminiNativeClient | **PORT** if gap | endpoint-scoped health |

---

## Additional keyword scan (`b51c055..upstream/main`)

Relevant themes observed (not all PORT):

- Update / fleet / Windows resume token — mostly already composed; gateway-kind expectation still missing
- Credential pool admin / OAuth refresh CLI — PORT CLI
- Desktop artifact / profile / session targeting — verify + selective PORT
- Approval / gateway privacy — **SKIP** unless Windows-observable contract gap proven
- MCP device OAuth — **SKIP** this campaign (out of Windows semantic carry scope unless blocking)
- Cron / TUI drain ownership — **SKIP** unless directly tied to PTY/update contracts

---

## Downstream contracts that must not regress

```text
Windows native Python / Electron Desktop
Go watchdog outer recovery authority + maintenance lease
handle-bound backend teardown (no PID-only taskkill)
NTFS / PowerShell / installer+portable+upgrade paths
local llama.cpp / GGUF / embedding supervision
Semantic Graph / Ebbinghaus / VRChat / VOICEVOX / AITuber / Hypura
provider rotation/fallback
Chrome/Edge → hermes://open/browser hand-off
security hardening / credential isolation
FEATURES.yaml / CARRY.yaml / WINDOWS_PLATFORM_CONTRACT.md
```

## Explicit SKIP list

| Item | Why |
|------|-----|
| `git merge` / `rebase` / mass cherry-pick of `upstream/main` | Forbidden |
| PR #102117 structural mirror / COMPAT_MANIFEST giant shim | Architectural reference only |
| Moving `UPSTREAM_SNAPSHOT` / treating moving `upstream/main` as release baseline | Frozen SHA stays historical |
| Deleting Go watchdog / Python restart authority takeover | Downstream stronger |
| Broad `taskkill /F` / PID-only backend kill | Security contract |
| WSL escape for Windows-native paths | Forbidden |
| Replacing Semantic Graph with upstream memory | Downstream feature |
| Removing Browser hand-off for “upstream purity” | Downstream-owned |
| Fail-open to make tests green | Forbidden |

## Browser hand-off preservation (Task 14)

Current: `hermes://open/browser?url=…` → `pathFromHermesDeepLink` → `/browser?…`.

**Class: ALREADY_EQUIVALENT** for routing shape; characterisation tests must lock:

- http/https allowed; javascript/file/hermes-nested rejected
- blank open/browser brings Browser pane forward
- invalid browser URL must not fall through to generic `/browser` incorrectly
- remote artifact routing ≠ Browser external URL routing

---

## Implementation order (after this matrix)

1. Characterisation tests for post-snapshot contracts
2. ConPTY async write + PtySession generation + WS 1013 stalled close
3. `HERMES_PTY_HOST` + focus restore (no focus steal)
4. COMPOSE staged promotion re-quiesce + second wait
5. Fleet gateway-kind expectation
6. Auth priority/refresh CLI into existing pool
7. Fallback loop + probe credential semantics
8. Remote artifact + profile fail-closed differential tests
9. CARRY.yaml only for true downstream adaptations
10. Native Windows qualification

## Commit boundaries (recommended)

```text
docs(windows): record upstream carry matrix 2026-09-08
test(upstream): characterize post-snapshot Windows contracts
fix(win-pty): make dashboard input cancellation-safe
fix(dashboard): preserve PTY ownership across app switches
fix(update): compose staged promotion with Windows lifecycle authority
fix(update): scope fleet verification to gateway runtimes
fix(auth): carry pooled credential administration semantics
fix(agent): preserve fallback cooldown and endpoint health semantics
fix(desktop): preserve remote artifact and profile provenance
test(windows): qualify post-snapshot upstream semantic carry
```

## Verification plan (evidence required; no speculation)

| Lane | Command | Status at matrix time |
|------|---------|------------------------|
| CodeGraph | `codegraph query/explore/impact` | RUN — used for classification + mid-carry gap check (`shouldRestoreTerminalFocus` absent → PORT'd; `try_activate_fallback` recursive → PORT'd to `while True`) |
| Python focused | pytest PTY/update/credential/downstream/profile/auth contracts | **PASS** (fresh) — downstream+profile+probe **14 passed, 1 skipped**; auth priority/refresh/reset/list **6 passed**; earlier PTY/fleet **56 passed, 3 skipped** |
| Ruff / compileall / `git diff --check` | as spec §26 | **PASS** (scoped) — `git diff --check` no conflict markers (CRLF warnings only) |
| Desktop | package-manager from lockfile (`npm`/`pnpm`) | **PASS** (focused) — UI **39** + electron **26** = vitest **65 passed**; full pack NOT RUN |
| Go watchdog | `go test ./...` under `scripts/windows/watchdog-go` | **PASS** |
| Desktop before-pack DI | `node` import of `releaseInstallScopedDesktopLocks` + vitest | **PASS** (12) |
| Native Windows physical | ConPTY + Desktop + watchdog + Browser hand-off | **PASS** (delivery) — ConPTY live; install-scoped restart; fresh `[deeplink] delivered open/browser` @ 18:47:42Z / fire 03:47:41 JST; pixel screenshot optional |

## Mid-carry status (2026-09-08 Composer)

| Candidate | Status |
|-----------|--------|
| ConPTY async write + PtySession gen + WS 1013 | **PORTED** (prior checkpoint) |
| Fleet `kind == "gateway"` | **PORTED** (prior checkpoint) |
| Staged Desktop second `wait_procs` | **PORTED** (prior checkpoint) |
| Staged Desktop pre-rename re-quiesce (`f17f18`) | **COMPOSED** into in-place pack: `before-pack.mjs` `releaseInstallScopedDesktopLocks` immediately before live rename/wipe (no `main_desktop.py`) |
| `HERMES_PTY_HOST` spawn env | **PORTED** (prior) |
| Ink dashboard skip erase+repaint + `termio/host.ts` | **PORTED** this turn |
| `web/src/lib/pty-focus.ts` + ChatPage Alt-Tab restore | **PORTED** this turn |
| Fallback cooldown single-loop (`fc70d05`) | **PORTED** this turn |
| Auth priority/refresh CLI | **PORTED** this turn (`move_entry`/`reset_status`/`status_cleared_ids` + `hermes auth priority|refresh|reset <target>`; list shows id+priority) |
| Remote artifact provenance (`f9d050`/`478d772`) | **PORTED** — tilde/relative stay gateway-owned; originating `sessionId`/`profile` on download; `_fs_path(..., cwd=)`; UNC still fail-closed on fork |
| Profile fail-closed (`026e3e84`) | **PORTED** — `_profile_home` raises; `config.get`/`config.set` `@_profile_scoped`; `tools.configure` stale `session_id` → 4001 + **zero** `save_config` |
| Gemini `google` alias (`a745101`) | **PORTED** |
| Probe credential mint (`7d44fe9`/`bbbccd`) | **PORTED** — `materialize_probe_api_key` + no fallthrough on failed callable |
| Provider setup profile ownership (`0b3391322c`) | **COMPOSED** — settings scope remount + `targetProfile` / `flowGeneration` cancel-late; OAuth helpers `profileScoped(profile)` ([Review](e6c79796-6a18-481c-9d58-439abdef4358#changes)) |
| Staged Desktop re-quiesce before live rename | **COMPOSED** — `apps/desktop/scripts/before-pack.mjs` `releaseInstallScopedDesktopLocks` (in-place pack; not upstream `main_desktop.py` stage-and-swap) |
| Checkpoint junk (`.tools/npm-cache`, scratch) | **DROPPED** — committed as `50b30d8719` (27 paths / 911 deletions) |

## Provenance fields for final report

```text
source_upstream_head: a7198a8855ad98681114ff5138eb01fe132a62e7
downstream_start_head: 37aade8afb6ff944dfbe1b6ee32485b1b1c71e3e
frozen_upstream_snapshot: b51c055a12220f8c7c18660e8599365012e19532
candidate_commits: (see sections above)
qualification_result: COMPLETE
# Audit 2026-09-08 (Composer completion audit): tip e118f4006e includes
# 50b30d8719 (junk drop) + PORT/COMPOSE carry; tracked tree clean aside from
# intentional EXCLUDE untracked FEATURE_LEDGER / PARALLEL_OWNERSHIP;
# UPSTREAM_SNAPSHOT unchanged at b51c055; CARRY.yaml + matrix + tests in tip;
# fresh pytest/vitest/deeplink evidence in _docs (commit-ready qual + deeplink).
# Cursor CreateGoal/UpdateGoal MCP tools were NOT present in this session —
# engineering qualification is COMPLETE; Goal UI status may still need operator.
```
