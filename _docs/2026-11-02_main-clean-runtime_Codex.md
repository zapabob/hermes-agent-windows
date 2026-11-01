# Main cleanup, commit, desktop rebuild and runtime verification

## Requirements and standards

Date: 2026-11-02 JST. Operator requested a clean worktree, commit and normal push to main, a Desktop rebuild, and running llama and Go services. Acceptance requires preservation of existing work, packaged Desktop output, and fresh service evidence. This record does not claim formal MILSPEC certification or a comprehensive security assessment.

Read PC/Codex/project/Desktop AGENTS, the canonical CLAUDE-FABLE-5 prompt and applicable common engineering, implementation gate, skill selection, security, application development, AIOps, LLMOps, Python, TypeScript and Go SOPs. Applied codex-session-style-and-standards, milspec-codex-standard, hermes-agent, git-workflow-and-versioning and build-manager. Higher-priority runtime instructions override incompatible prompt identity/environment/tool examples.

## Initial state and preservation

Canonical Documents checkout: main at 1f4b8ae0bc6, 27 modified tracked files, two new security files, an incomplete config module, scratch probes, build outputs and vendor/airi output. Fetch found eight newer origin/main commits, ending at 018fc751315.

Saved the original tracked binary diff to tmp/probes/20261102-main-clean/tracked-before.patch. Moved twelve root scratch files, including a local database and an A2A report, into that ignored directory. Also preserved hermes_cli/config_effective.py there: it imports absent config_read_errors/config_backups modules and calls absent config cache helpers. This incomplete file is preserved rather than shipped or deleted.

Added checkout-local exclude entries for .build/, apps/desktop/dist-webapp/ and vendor/airi output/. Data remains in place; shared ignore policy was not changed. Preserved the other registered H:/hermes-worktrees/pr158-harness worktree. No reset, clean, force push or submodule revision change.

A zero-byte .git/index.lock dated 2026-11-01 19:46 JST blocked staging. No git process was live and the lock was over four hours old. Preserved it as tmp/probes/20261102-main-clean/stale-index.lock before staging.

## Existing implementation saved

Dependency commit aligns pyasn1 0.6.5 across pyproject, lockfile and Google runtime installers, with existing tests. Security commit saves existing profile-scoped posture API/UI/report implementation, watcher ownership checks, execution-gate environment assignment handling, translations and tests. Runner commit recognises uv Windows environments without activation scripts. Rebased all three onto origin/main without conflicts.

## Verification

Used Git for Windows Bash explicitly because PATH bash selects WSL without /bin/bash. scripts/run_tests.sh selected the existing project venv and isolated test files. First run: tests/security/, blue-team script tests, Google Chat dependency tests, Google Workspace setup tests and lazy dependency tests: 16 files, 314 passed, zero failed, five skipped, 135.6 seconds. Post-rebase repeat pending.

Desktop security Vitest: 10 passed. Desktop typecheck and targeted ESLint passed before rebase. Targeted Python Ruff passed. uv lock --check --offline passed, 270 packages. git diff --check and staged checks passed. Added-line credential-pattern check found no recognised provider tokens/private keys. Optional Git hook reported lefthook missing; explicit validation was run instead.

Used uv run --no-sync to preserve the running environment: installed .venv Python 3.12.13 meets requires-python, while .python-version requests 3.11. uv warns about this request mismatch. No Python environment replacement or dependency sync was performed.

## Build and runtime

Started uv run --no-sync python -m hermes_cli.main desktop --build-only --force-build --hermes-root <canonical> with Hermes-managed Node 26.12.1 first on PATH. Log: tmp/probes/20261102-main-clean/desktop-build.log. The project packaging path owns output lock release and rollback handling.

Before rebuild: llama on 8080 /health and /v1/models returned HTTP 200 with Hikari-LoRA-fixed-scale-PQ2_0 loaded. Go watchdog on 9920 /health and Go A2A round-robin on 9124 /health returned 200. Go A2A hub on 9123 /status returned valid JSON; /health is not its route. Healthy servers were retained without duplicates, GPU-clock changes, broad termination, remote message sends or elevation changes.

Go watchdog state indicated an existing intentional Desktop stop lease. Its health endpoint proves the watchdog HTTP service is alive; automatic recovery status must be checked again after Desktop launch.

## Completion evidence and limitations

Build completion, post-rebase checks, launch and remote SHA receipt will be recorded before handoff. Full repository CI, live posture auditing, all optional engines, real message delivery and model generation are outside this bounded task. Five parity tests used existing skip conditions. Scratch backups remain local and available.

## Post-rebase verification update

Repeated parity tests after rebase: 16 files, 314 passed, zero failed, five skipped, 150.6 seconds. Normal push to origin/main succeeded at ad48a9c36b733fef9a6f742f22bdde500a1a1382, verified with git ls-remote. GitHub reported required CI checks expected at push time; this is not evidence that all remote CI passed. Dependency Graph and Docker jobs subsequently reported success while main CI remained pending/running.

The canonical Desktop command completed dependency reinstallation and began renderer compilation. A post-rebase Prettier check identified formatting differences in four changed UI files. They will be corrected after the active build finishes, then the project pack command will regenerate the final artifact using the already installed locked dependencies.

## Final package and launch update

The canonical build-only command succeeded. After renderer compilation finished, Prettier corrected four UI files (14 inserted/7 removed lines), with no logic changes. Targeted ESLint passed again; Prettier now passes. Post-rebase Desktop security Vitest passed all 10 tests, and complete Desktop typecheck passed. The formatting-only source commit is a9dd1ac47e471ac01e6f30bf8d276bb34105246f.

Regenerated the final Windows package using pnpm --dir apps/desktop run pack with the already installed locked dependencies; exit 0. Final packaged install-stamp records a9dd1ac47e471ac01e6f30bf8d276bb34105246f, main, dirty=false. Hermes.exe is 235409920 bytes, modified 2026-11-02 00:48:19 JST, SHA256 AF58ED47554D7874C0C280AF8BB11DF5F4D2C840EF886AFD8FD4FF751D55FA55. Previous package is retained by the existing before-pack rollback hook.

Initial launch exposed EPIPE after the command output pipe closed. Relaunched through the existing canonical PowerShell launcher in a detached hidden helper with stdout/stderr redirected to tmp/probes/20261102-main-clean/desktop-launch.*.log. Normal window close did not finish within eight seconds, so only the exact verified canonical Hermes main PID 8628 (path and start time checked) was stopped. New main PID is 16156. No generic Python/Electron tree termination was used.

Computer Use display inspection was unavailable: its listWindows call failed because the Codex app-server path is missing (os error 3). No screenshots or UI state claims are made. Window process metadata and backend HTTP readiness provide the startup verification instead.

An additional read-only SQLite scratch probe, _p5.py, appeared during the task. Copied it into the preservation directory and added an exact checkout-local exclude entry while leaving its original in place for its creator.

## Final runtime evidence and upstream formatting reconciliation

At 2026-11-02 00:52:49-57 JST, HTTP 200 was verified for Desktop backend 127.0.0.1:56271/api/status, llama :8080/health and /v1/models, Go watchdog :9920/health, Go A2A hub :9123/status and round-robin :9124/health. Evidence: tmp/probes/20261102-main-clean/runtime-after.json (status/time only, no response bodies). Desktop main PID 16156 had a Hermes window handle and Responding=true. Watchdog reported maintenanceState=NORMAL, desktop=up, backend=up, backendPid=28172, backendPort=56271 and backendHealth=healthy. Its earlier intentional stop fence cleared through the normal Desktop lifecycle. Existing llama and Go processes were retained.

During the build, GitHub's existing JS formatting bot merged PR #195, advancing origin/main to 6a5158fd54f4c0ec141b2f9b44e9e6eebff697dc. The bot contained the same four-file formatting patch plus blank-line formatting elsewhere. git diff -w --ignore-blank-lines between the built source commit and that main returned no Desktop source differences. Rebase automatically dropped our duplicate formatting commit as already upstream. The final binary retains the transparent a9dd1ac47e47 build stamp; runtime source is equivalent apart from whitespace. No functional change or third rebuild was necessary.

## CI limitations and policy repair

Windows Tier-1 run 41321887918 at ad48a9c36b7 failed on Node dependency advisory audit and stale carry metrics. The audit reported 34 findings (32 moderate, two high); JS dependency manifests and lockfiles were not changed in this task. No npm audit fix/force, advisory suppression or unrelated dependency upgrade was applied. Docker, Nix, Windows runtime authority and Windows downstream release workflows reported success on that source head; other CI was cancelled by subsequent activity. This is not an all-green CI claim.

Regenerated the two tracked carry-surface reports using scripts/downstream/carry_metrics.py after the bot merge, and verified --check. This repairs the policy output affected by our committed changes without changing runtime behavior. The implementation record and regenerated reports are committed and normally pushed as the final documentation closeout; remote HEAD equality and clean porcelain status are checked after push.

## Remaining limits

No UI screenshot was available because of the Computer Use helper path failure. No live model generation, outgoing A2A delivery, comprehensive dependency remediation or complete remote-CI qualification was performed. Existing test skip conditions and Python-version request warning remain as documented above. All root scratch backups and generated outputs remain local; no user conversation/state database was deleted or reset.
