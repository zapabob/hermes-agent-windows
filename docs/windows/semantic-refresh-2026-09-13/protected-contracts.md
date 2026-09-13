# Protected contracts — D0 baseline (7c697a8a)

Classification of `FEATURES.yaml` (18) and `CARRY.yaml` (24) at frozen D0.
Ledger status `verified` ≠ this campaign's Windows-native qualification.

## Legend

| State | Meaning |
|---|---|
| `IMPLEMENTED_AND_TESTED` | Source + named tests exist at D0; unit/contract runnable in isolated HOME |
| `IMPLEMENTED_NOT_QUALIFIED` | Present but live/soak/device qualification not claimed here |
| `DISABLED_OR_HOLD` | Explicitly off / HOLD; do not flip without evidence |
| `MISSING_OR_UNRESOLVED` | Cannot resolve owner/tests at D0 |

## FEATURES.yaml (18/18)

| id | Campaign state | Policy | Notes |
|---|---|---|---|
| windows-native-runtime | IMPLEMENTED_AND_TESTED | COMPOSE | Keep |
| go-watchdog | IMPLEMENTED_AND_TESTED | KEEP_DOWNSTREAM | Outer restart authority; no second supervisor |
| local-llama-gguf-runtime | IMPLEMENTED_AND_TESTED | COMPOSE | Keep; do not auto-download |
| llama-hotswap-hot-standby | IMPLEMENTED_AND_TESTED | KEEP_DOWNSTREAM | Operator-driven only |
| local-secretary | IMPLEMENTED_AND_TESTED | COMPOSE | Keep |
| hypura-local-provider | IMPLEMENTED_AND_TESTED | COMPOSE | Keep |
| semantic-graph-hybrid-retrieval | IMPLEMENTED_NOT_QUALIFIED | COMPOSE | Graph=authority; vector=derived. `abstention_enabled` default **False** — HOLD posture preserved |
| ebbinghaus-cognitive-memory | IMPLEMENTED_AND_TESTED | COMPOSE | Keep |
| vrchat-autonomy-tooling | IMPLEMENTED_NOT_QUALIFIED | COMPOSE | Live avatar NOT_RUN this campaign |
| unity-vrchat-bridge | IMPLEMENTED_NOT_QUALIFIED | COMPOSE | Live Unity NOT_RUN |
| local-voice-tts | IMPLEMENTED_NOT_QUALIFIED | COMPOSE | Device audio NOT_RUN |
| aituber-integrations | IMPLEMENTED_AND_TESTED | COMPOSE | Keep registration |
| osint-shinka-extensions | IMPLEMENTED_AND_TESTED | COMPOSE | Keep |
| desktop-git-review | IMPLEMENTED_AND_TESTED | COMPOSE | Keep |
| downstream-security-hardening | IMPLEMENTED_AND_TESTED | COMPOSE | Keep stronger boundaries |
| local-embedding-recovery | IMPLEMENTED_AND_TESTED | COMPOSE | Watchdog embedding lifecycle |
| provider-rotation-fallbacks | IMPLEMENTED_AND_TESTED | COMPOSE | Keep |
| watchdog-managed-desktop-backend | IMPLEMENTED_AND_TESTED | COMPOSE | Claim/prewarm; compose with upstream Desktop |

## CARRY.yaml (24/24)

All entries remain active. Do **not** retire on name similarity alone.

| id | Policy | Campaign note |
|---|---|---|
| terminal-environment-provider-bridge | COMPOSE | Keep |
| windows-docker-media-paths | COMPOSE | Keep |
| desktop-preview-surface-separation | COMPOSE | Browser ≠ file preview |
| watchdog-backend-prewarm | COMPOSE | Go Watchdog outer authority |
| windows-watchdog-lifecycle-fence | COMPOSE | Keep fence |
| codex-cloudflare-routing | COMPOSE | Keep |
| updater-noninteractive-network-git | COMPOSE | Keep |
| desktop-link-title-popup-fail-closed | COMPOSE | Keep |
| desktop-operator-startup-pages | COMPOSE | Keep |
| windows-desktop-handle-bound-teardown | COMPOSE | No PID-only kill |
| windows-conpty-pty-ownership | PORT | Prior campaign; verify vs U before re-PORT |
| windows-staged-desktop-promotion-locks | COMPOSE | Keep |
| windows-remote-artifact-unc-fail-closed | COMPOSE | Keep |
| desktop-browser-chrome-edge-handoff | COMPOSE | Protect `hermes://open/browser` |
| windows-system-ca-expiry-dedup | PORT | Check ALREADY_EQUIVALENT on U |
| relay-provision-secret-issued-f004 | PORT | Check vs U |
| tui-gateway-ws-send-deadline | PORT | Check vs U |
| desktop-queue-discovery-gate | PORT | Check vs U |
| cron-fire-claim-dead-owner-reap | PORT | Check vs U |
| desktop-native-notification-ipc-cluster | COMPOSE | Keep Windows approval fields |
| dashboard-auth-native-provider-chooser | PORT | Check vs U |
| desktop-oauth-sign-in-again | PORT | Check vs U |
| auxiliary-origin-async-progress | PORT | Check vs U |
| desktop-clarify-submit-shortcut | PORT | Check vs U |

## Sacred process / session / auth invariants (must not regress)

1. Go Watchdog ≠ Desktop backend ≠ Gateway ≠ model/embedding lifetimes.
2. Profile/session/generation consistent across events, approvals, DB, cache.
3. Missing explicit profile → refuse; never borrow default/sibling.
4. No Bot Chat forever-chat fork (name registry only).
5. Credential lease/identity bind; empty pool ≠ parent client fallback.
6. Prompt/tool schema hot-reload mid-conversation forbidden (except compression / explicit user change).

## Explicit non-touch

- `hakuapulse-orchestrator` MoA / model state
- Existing DISABLED/HOLD flags (semantic-graph abstention stays default off)
- Production Desktop/Gateway/Watchdog/llama processes
