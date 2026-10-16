# MCP parked OAuth refresh: Windows semantic adoption

Parent/restoration reference: `32d9952323f7d5e8bd5fee0b8fbb55c5c3be40a4`. Frozen upstream main: `63d0b94120027d487c9a5235b9ec64b696af1b26`; relevant change: `f7b26efc2ffa9c1380a7b8c3fad8c7331ab802e3`. ADAPT the behavior into the existing Windows registration path, without importing upstream module moves.

## Change and boundaries

`tools/mcp_oauth.py` exposes a metadata-only credential stamp on profile-bound storage. `tools/mcp_tool.py` captures that stamp when an OAuth authentication failure parks a task. Its real `register_mcp_servers` path suppresses ordinary discovery nudges while token/client-file metadata is unchanged; a changed stamp permits the existing reconnect. Explicit reconnect and timed parked self-probes remain available. Credential bytes are not read into the stamp. OAuth configuration binding, writer generations and locks are unchanged.

A writer update between the authentication failure and initial stamp capture may not trigger an immediate discovery wake. Timed self-probe and explicit reconnect remain available; immediate recovery under that race is not guaranteed. This is a bounded reconnect improvement, not a cross-process credential transaction guarantee.

## Validation

The new `tests/tools/test_mcp_auth_park_discovery_nudge.py` reproduced the externally visible defect: three discovery registrations signalled three reconnects after OAuth 401 with unchanged credentials, where zero were expected. The final behavioral RED is preserved. Earlier fixture setup and private-field failures are not product RED; the first setup raw log was overwritten and is not reconstructed.

GREEN: three files, four passed, zero failed, 11.8 seconds. Cohort: the new test, `tests/tools/test_mcp_register_wakes_stale.py`, and `tests/tools/test_mcp_parked_self_probe.py`. The tests cover unchanged-credential suppression, a new token saved through normal storage, explicit reconnect, normal stale-server wake and timed self-probe. Existing ROOT Windows Python and the process-per-file runner used isolated H HOME/HERMES_HOME/temp, UTC/UTF8, removed provider credentials, and `--jobs 1 --file-retries 0 --file-timeout 300 -q` with a semicolon-separated file list. No live provider or service action was used.

CodeGraph linked the actual registration caller before edits; one incremental sync processed three changed files. Post-sync status: 9,173 files, 198,271 nodes, 625,436 edges, zero pending changes/refs, extraction25 current. The stamp's callers are the OAuth park operation and registration. A separate Luna MAX reviewer returned specification and quality PASS, no blocker, with the recovery-timing qualification above. No upper-model repair was used.

## Evidence and recovery

Local evidence in `H:/Codex-v0216-archive/`: `V0217_PARKED_REFRESH_CLOSEOUT_20261013.md`, `V0217_PARKED_REFRESH_INDEPENDENT_REVIEW_20261013.md`, `V0217_PARKED_REFRESH_PRODUCT_RED_20261013.txt`, `V0217_PARKED_REFRESH_GREEN_20261013.txt`, and `V0217_PARKED_REFRESH_CODEGRAPH_STATUS_20261013.txt`. Commit receipt: `V0217_PARKED_REFRESH_LOCAL_COMMIT_RECEIPT_20261013.json`. Raw logs, DBs and credentials are not committed.

Recover using a targeted revert of this unit on the isolated branch after checking later dependencies. The parent SHA identifies the exact prior source. Do not reset PRIMARY or include unrelated dirty files. Full Windows0.21.7 adoption, version update and actual packaged acceptance remain open.