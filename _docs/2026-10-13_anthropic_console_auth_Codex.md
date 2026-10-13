# Anthropic Console authentication: Windows semantic adoption

Frozen upstream: NousResearch/hermes-agent main at `63d0b94120027d487c9a5235b9ec64b696af1b26`. Parent and restoration reference: `a88f34ec32a2f9733187bb73f6e8f5da5c5ef5bf`. Scope is a local, reviewed authentication change; no release or live service update.

## Behavior and disposition

ADAPT Console API-key classification for `sk-ant-api`, `sk-ant-usr`, `sk-ant-svc`, and `sk-ant-admin`. Native Anthropic callable credentials use `x-api-key` for API keys. OAuth credentials, custom endpoint bearer authentication, and the default Azure/Entra bearer hook behavior remain supported. Exact-host validation prevents a lookalike endpoint from selecting native-host behavior.

Owners: `agent/anthropic_credentials.py`, `agent/anthropic_adapter.py`, and `agent/azure_identity_adapter.py`. Two new tests are `tests/agent/test_anthropic_client_auth.py` and `tests/agent/test_anthropic_route_oauth_identity.py`; existing adapter tests were not rewritten.

The helper's explicit-provider fallback is not connected through the current production builder. It is not accepted as complete upstream provider-route parity and remains a follow-up in the model/provider unit. Focused builder/request-hook tests and source caller review do not establish live CLI/Gateway credential-provider integration.

## Validation and independent review

The implementation worker observed a pre-change RED of 5 passed and 6 behavioral failures. A separate preserved raw RED log is not included in the evidence packet; this observation is weaker evidence than the saved GREEN runs.

Windows native runner: `scripts/run_tests_parallel.py --files <semicolon-separated files> --jobs 1 --file-retries 0 --file-timeout 300 -q --basetemp=<isolated H path>`, using existing ROOT Python, fresh file subprocesses, UTC/UTF-8, sanitized environment and isolated HOME. Existing H launcher was imported with in-memory cohort and path overrides; no live credentials/API calls.

Three Anthropic files: 107 passed, zero failed, one existing POSIX mode-bit skip, 11.2 seconds. Azure identity adapter: 19 passed, zero failed, 3.3 seconds. No NTFS ACL qualification is inferred. CodeGraph owners/callers were checked before edits; one incremental sync processed the five changed source/test files successfully.

A separate Luna MAX reviewer returned spec PASS and quality PASS for native-host Console/OAuth headers plus custom-route/Entra bearer preservation. It qualified the unwired explicit-provider fallback above. No higher-model repair was used.

## Local evidence and recovery

Evidence directory: `H:/Codex-v0216-archive/`. Index: `V0217_CONSOLE_AUTH_CLOSEOUT_20261013.md`; review: `U01_AUTH_INDEPENDENT_REVIEW_20261013.md`; logs: `U01_AUTH_FOCUSED_RUN_20261013.txt`, `U01_AUTH_AZURE_RUN_20261013.txt`, `U01_AUTH_CODEGRAPH_SYNC_20261013.txt`; commit receipt: `U01_AUTH_LOCAL_COMMIT_RECEIPT_20261013.json`. The intake report and complete tree delta retain the frozen upstream sources. Raw logs, databases and credentials are excluded from this commit.

Recovery is a targeted revert of this unit's commit on this isolated branch, after checking for later dependent changes. Parent `a88f34ec32a2f9733187bb73f6e8f5da5c5ef5bf` remains the exact pre-change source. Do not reset PRIMARY or include the unrelated dated adoption log. Full Windows 0.21.7 acceptance and version update remain pending.