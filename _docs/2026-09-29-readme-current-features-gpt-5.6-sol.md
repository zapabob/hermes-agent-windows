# 2026-09-29 README current-feature alignment — GPT-5.6 Sol

## Scope

Rewrite the public README set so it describes the current Hermes Agent Windows
Workstation Edition implementation at product version 0.21.5 without treating
that version string as proof that the active semantic-refresh campaign is
complete.

Base before this documentation commit:
`3c0fe9b0f04` (`origin/main` at validation time).

## Implemented documentation changes

- Rewrote `README.md` around the current Windows workstation architecture and
  operational boundaries.
- Synchronized the Japanese and Simplified Chinese READMEs for the same product
  version, semantic-refresh boundary, plug-in inventory policy, Bot Mode identity,
  `implementation_router` scope, and Control MCP write gate.
- Removed brittle fixed plug-in/provider counts from the public README contract.
  Runtime inventory now points to `uv run hermes plugins`, while the broader
  snapshot remains in `docs/windows/INTEGRATIONS.md`.
- Documented upstream stable R2
  `f97608f178d1ffeca59860195ab7da295f7c8e5f`, active frozen ceiling U1
  `678a4762b887f3eabe5cad11254b2ab1ae859485`, and historical provenance snapshot
  `b51c055a12220f8c7c18660e8599365012e19532` as distinct concepts.
- Documented Electron main as the destructive Desktop-backend lifecycle owner.
  The Go watchdog remains auxiliary and may destructively manage only an
  embedding `llama-server` instance that it launched and owns.
- Documented normal provider/model selection, OAuth/API-key/custom/local routes,
  fallback, ordinary delegation, MoA and reasoning effort as independent
  capabilities.
- Documented Semantic Graph and Ebbinghaus memory roles, Security Center, and the
  Bot Mode canonical identity `(profile, "Bot Chat")` without a persisted
  canonical session-id pointer.
- Documented `implementation_router` as an opt-in isolated engineering workflow;
  it does not replace the normal picker/delegation/MoA/fallback paths and does
  not apply or publish changes by itself.
- Kept Control MCP production write explicitly `DISABLED`. N07-A1, T06 and T12
  remain open evidence gates; this README change does not authorize production
  writes.

## Validation

Executed after fast-forwarding the isolated documentation worktree to the then
current `origin/main`:

```text
python -m pytest tests/downstream/test_readme_contract.py \
  tests/downstream/test_distribution_metadata.py \
  tests/test_project_metadata.py -q

28 passed
```

`git diff --check` also passed. The only Git message was the existing Windows
line-ending warning for `README.md` (`CRLF` working copy to `LF` on Git write),
not a whitespace-error failure.

## Qualification boundary

This change updates documentation and README contract tests. It does not claim
that every upstream ledger row is semantically adopted, that Control MCP
production write is enabled, that a stable installer has been published, or that
the Desktop/backend/llama/embedding/Go runtime restart has been completed.
