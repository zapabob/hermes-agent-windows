# Frozen upstream policy

The original integration campaign accepts one immutable upstream input:
`b51c055a12220f8c7c18660e8599365012e19532`. The input was captured at
`2026-09-05T17:00:27.3045850+09:00`. Later commits on `upstream/main` are explicitly out of scope
and must not be resolved, fetched, or substituted by automation.

Later work selects an explicit campaign ID through the frozen records named
in `.codex/SOP.md`. The `windows-semantic-refresh-20260926` campaign is based
on the user's 2026-09-26 request and its independent
`docs/windows/semantic-refresh-20260926/freeze.json`. Its U1 ceiling does not
replace this historical snapshot or the workstation-20260924 U0 ceiling.
Automation must never infer a newer ceiling from a moving remote ref.

The recorded downstream start is `e8a7d7a6a52a8e6ae1defbe07bdee92472be1b2b`. The verified repository
merge base is `1fe0f2f3ac9748ce799272eb93bee2937b5ab802`. Semantic three-way review uses the previous
frozen upstream `5a8e8a6b87487c0e0785cd9eb561cc6a96c64f5e` as BASE.

Official public contracts are the preferred integration boundary. Security,
data-integrity, and credential-boundary fixes are adopted unless the
downstream property is demonstrably stronger, in which case the result is a
composed implementation. Overlapping capabilities retain the official
contract and preserve verified Windows or local-AI advantages as a narrow
downstream layer.

Snapshot tooling may enumerate, classify, and generate deterministic reports.
It must not resolve latest, fetch a moving upstream branch, choose ours or
theirs, delete downstream features, or resolve semantic conflicts. All
semantic integration is reviewed against `UPSTREAM_ADOPTION.yaml`,
`FEATURES.yaml`, `CARRY.yaml`, and the fork invariants.
