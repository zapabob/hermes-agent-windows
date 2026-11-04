# Daybreak Desktop port — local review candidate

Date: 2026-11-04. This is a local implementation receipt; no remote branch, PR,
release, or installed Windows runtime was changed as part of this preparation.

## Frozen comparison

- Windows fork: `24f89ab7bc09b3382d45edd464fc28e32f28ec66`.
- Upstream v0.22.7: `b200f5bc60e31588ba2cb60e288029c4a54ba5fa`.
- Origin: [upstream Daybreak store](https://github.com/NousResearch/hermes-agent/blob/b200f5bc60e31588ba2cb60e288029c4a54ba5fa/apps/desktop/src/store/daybreak.ts)
  and [Codex capabilities](https://github.com/NousResearch/hermes-agent/blob/b200f5bc60e31588ba2cb60e288029c4a54ba5fa/agent/codex_service_tiers.py).

## Design and scope

The existing Windows `ModelMenuPanel`, speed/reasoning controls and optional
catalog controller remain the integration points. A connection/profile-owned
store queues writes and rolls back to the last confirmed value on refusal.
Tuple keys distinguish the launch profile from an explicit `default`; reads
started while a write is pending cannot later overwrite the confirmed save.

Only built-in official Codex rows with an exact account-catalog entitlement
receive a control. Normal inventory remains cache-only. Unknown/expired
entitlements and user-defined provider rows do not gain this automatic control.
This is a conservative UI boundary, not proof of service-side ineligibility.

The Daybreak setter writes `agent.daybreak` with the existing atomic leaf writer
and an explicit active-profile path. The legacy general writer targets the
launch home and is not used for this new key. Managed settings are rejected;
save failures do not change a live agent. A successful save invalidates the
read cache. The real gateway turn admission synchronizes the final selected
agent inside its existing profile scope.

The request builder copies overrides and checks the selected credential, exact
effective model, provider and official URL before adding the access program.
It preserves Fast Mode and reasoning settings. It does not mutate the stored
override dictionary or inject Daybreak into unsupported subsequent requests.
The target is Desktop/TUI-gateway turns, not all upstream CLI/surface changes.

No Windows process-management, watchdog, local-model launcher, dependency lock,
product version, prompt history or past-context implementation was changed.

## Verification record

- Desktop targeted regression: 8 files / 79 tests passed; typecheck and target
  ESLint passed. Includes the real panel, scoped store, catalog, submenu,
  presets, kanban overrides and native-picker contract tests.
- Baseline behavioral failures were established for the missing submenu/panel
  integration and for three races/key cases in the unmodified upstream store.
- Python regression uses actual RPC handlers, temporary config files,
  `build_api_kwargs`, the Codex transport and real turn admission with unrelated
  dependencies stubbed. Removing the turn synchronization makes its test fail.
- Broad Desktop diagnostic: 9,265 passed, 11 failed, 15 skipped. The same 11
  native process/network-interface failures reproduce on the three unchanged
  baseline Electron test files (148 passed / 11 failed).
- CodeGraph query/explore/impact informed ownership; full-repository indexing
  stopped with exit 137. This is not a complete graph-based proof.

The accompanying review package records exact commands, final offline Python
results, interrupted checks, baseline/candidate logs, applicable patch and SHA
manifest. Counts from overlapping suites must not be added together.

## Remaining gates

Windows Electron build/run, ACL/atomic-replace refusal, real account catalog
refresh, reconnect/profile switching, live model responses and existing local
GPU routes still need Windows validation. No live subscription/model inference
is claimed. The leaf writer does not add a cross-process read-modify-write lock;
tests cover unrelated edits completed before a save begins.

User approval is required before any branch push or PR creation. Approval to
prepare this candidate is not approval to merge it or release a binary.
