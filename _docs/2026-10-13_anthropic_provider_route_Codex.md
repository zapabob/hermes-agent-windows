# Preserve explicit Anthropic OAuth identity through client reconstruction

Frozen upstream main: `63d0b94120027d487c9a5235b9ec64b696af1b26`; related change: `4e745c539893422cc5509b167350049702e948ee`. Local parent and recovery reference: `e480e78655317781ef289f3bc6216c9424e062bc`.

## Behavior adopted

ADAPT the provider-aware OAuth route into the existing client factory and its actual callers. An explicitly configured Anthropic provider using a compatible proxy keeps OAuth bearer authentication and Claude identity headers. Initial agent construction previously recognized this route as OAuth but constructed the SDK client with API-key arguments because it omitted the provider identity.

The optional provider argument now follows the selected route through initialization, model switch, fallback, primary restore, transport recovery, request-client construction, credential refresh/swap/rebuild, and the dedicated Anthropic auxiliary path. Restore and fallback paths use their restored or selected provider. Generic custom/third-party auxiliary routes retain their existing identity; OAuth-shaped credentials alone do not grant a custom route Anthropic identity. Existing API-key, callable-key/Entra and bearer/Kimi precedence are retained. No mandatory environment variables, configuration schema changes, dependencies or upstream module rearrangements are introduced.

## Acceptance

A real AIAgent initialization path, with the external SDK constructor captured locally, first failed because the expected OAuth auth_token argument was absent. The focused GREEN then passed 19 cases across route identity, client authentication and auxiliary custom-client tests. Four selected existing tests also passed: switch failure rollback, Nous Anthropic-format fallback, fallback-to-primary restore, and Nous Anthropic transport recovery. All 23 cases passed with no skips. Initialization tests additionally exercise credential refresh and client rebuild.

Tests used ROOT's native Windows Python and the existing process-per-file runner, one worker, zero retries, a 300-second file timeout, fresh H-only HOME/HERMES_HOME/basetemp, UTC/UTF-8 and an allowlisted environment without provider credentials. The focused GREEN log inherited an incorrect one-file/filter preamble; the saved runner argv, three per-file result rows and 19-case summary establish what actually ran. The discrepancy remains in the raw evidence. No live provider call or full UI/package acceptance is claimed.

CodeGraph mapped actual constructors and callers. One incremental sync updated eight changed files and 1,187 nodes. Parent read-only verification confirmed ROOT identity, complete graph state, 9,177 files, zero pending changes/references and current extraction version 25. No second sync or database copy was used. Independent Luna MAX review verified source pins and evidence and returned specification and quality PASS for this bounded contract.

## Evidence and recovery

Local evidence directory: `H:/Codex-v0216-archive/`. The source pins, commands and log hashes are indexed by `V0217_MODEL_PROVIDER_ROUTE_CLOSEOUT_20261013.md`; independent verdict is in `V0217_MODEL_PROVIDER_ROUTE_INDEPENDENT_REVIEW_20261013.md`. Raw results are `V0217_MODEL_PROVIDER_INIT_RED_20261013.log`, `V0217_MODEL_PROVIDER_GREEN_20261013.log`, and `V0217_MODEL_PROVIDER_REGRESSION_20261013.log`. Parent graph verification is `V0217_MODEL_PROVIDER_CODEGRAPH_STATUS_20261013.json`. The commit receipt links exact staged/committed blobs and protected-state checks. Logs, databases, credentials and unrelated local materials are excluded from the commit.

Recovery is a targeted revert on the isolated branch after checking later dependencies, using the parent above as the prior source. Do not reset PRIMARY or discard unrelated work. This closes the explicit-provider caller follow-up from the earlier Console-auth unit; complete model-selection UI semantics, dead-host cancellation recovery, Windows execution/resource/memory contracts, real package acceptance and the 0.21.7 version update remain separate requirements.
