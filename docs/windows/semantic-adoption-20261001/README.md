# Windows semantic adoption, 2026-10-01

This is the additive campaign record for the user's Windows-native feature adoption request. The intake specification remains the supplied `hermes_windows_semantic_adoption_20261001.zip`; its contents are inputs, not execution evidence. Historical `.codex/UPSTREAM_SNAPSHOT.json`, semantic-refresh-20260926, N/LM/T cards, and U1 receipts are unchanged.

Frozen inputs are R_BEFORE `63279301bcbdc185c1b07b98a9312eb0c862f26d`, R_AFTER `d3630f853239e8c41ce7201e09fbdf39bcbc5431`, U_TARGET `1a269fcd3b61971bd05e841f80154279dd0a7e65`, and D_BASE `a553729853b9648bf8ca9e5c3c7e54365d7f5c62`. Integration starts at D_BASE. The direct user request authorises this separate fixed campaign; the older `.codex/SOP.md` frozen-input clause continues to describe its historical campaign and is not rewritten.

The first feature is F03, `/s` as an alias of the existing `/steer` owner. F01 queue management follows; F02 branching and F04 Desktop metadata remain independent slices. A registry alias alone is insufficient: public entry, busy dispatch, actual effect, session/profile isolation, negative controls, mutation, fresh graph binding and independent review must all be evidenced.

The implementation plan remains open. Initial full-history extraction returned 4,272 refactor-window rows and 14,548 post-refactor rows. Static command counts are 101 for R_BEFORE/R_AFTER and 102 for U_TARGET/D_BASE; all behavioral dispositions remain unreviewed. These counts do not measure parity. The 50 seed candidates are neither the complete contract inventory nor a completion denominator.

Machine-local receipts are retained outside the product checkout in the isolated campaign workspace. They include intake digest verification, exact roots/HEAD/tree observations, tool provenance, provisioning, inventory and test output. Do not commit the graph DB, local environments, credentials, process state or raw machine inventory.

The approved CodeGraph 1.6.0 runs through Node 22.23.2 and bundled Node 24.16.0 with downloads and telemetry disabled. Initial integration/U_TARGET indexes failed with `database is locked`; subsequent full builds completed. Read-only database-to-source verification covered 8,960 files each in integration/D_BASE, 8,774 in R_AFTER and 13,040 in U_TARGET with no source-hash mismatch. Generation stamps are version 1.6.0/extraction 25. The tool's hard-coded 1 MiB cap excludes downstream `gateway/run.py` (1,576,015 bytes, zero nodes) and `UPSTREAM_ADOPTION.yaml`. Complete/pending-zero status does not resolve this coverage gap.

F01, F02 and F03 acceptance remain BLOCKED_CODEGRAPH because the Gateway public caller is excluded. There is no tool modification, source splitting, private database insertion or substitute graph. F02 read-only owner audit found substantive gaps in `--here`, thread destinations, parent prompt inheritance and CLI child-first/mid-turn behavior; these are candidates for later reproduction, not implemented fixes.

F05a is a separate, limited feature slice on fully indexed display sources: live-language CLI help/completion, shared help text, English fallback and three source-equivalent command descriptions. It does not change dispatch, availability policy, registry identity, model selection or security. The fixed mini-plan defines its acceptance boundary. The remaining F05 translations/surfaces and all other seed families remain open.

The D_BASE F03 baseline executed the repository's canonical per-file runner on native Windows in a new test environment: 63 passes, zero failures, three files. One pre-existing repaint test inspects AST shape, so that file is not accepted as end-to-end behavior proof. New tests must execute runtime behavior.

Protected baseline: 121 passes, one YARA failure and one real-ClamAV skip. The YARA failure came from provisioning only `dev`; the frozen lock already supplies optional `security` extra yara-python 4.5.4 and a Windows cp311 wheel. It was added only to the dedicated test environment, without changing dependencies or product scanner code. ClamAV native engine/definitions remain an unfulfilled acceptance gate. Do not convert their skip into scanner proof.

No full-U_TARGET parity, 0.25 compatibility, production stability, runtime independence, CI success, release readiness or completion is claimed. Main push/merge, release, version changes, deployment and production restart are outside this task's authorisation.

F05a bounded acceptance is verified: 118 final targeted regression passes, 11 post-restore acceptance passes, four detected mutants with exact-byte restoration, corrected name-based CodeGraph impact with parsed JSON and exact owner inclusion, and independent Sol high source/evidence approval. Earlier ID-based impact outputs are rejected. Same-name CLI impacts are merged; exclusions and campaign incompleteness remain explicit. F05a.json records the final hashes and commands.
