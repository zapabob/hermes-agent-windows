# Frozen parent inventory and native HTTP checkpoint — 2026-10-16

This checkpoint follows local U02 commit
`54c6f5680033c3d7ae8364ab3ad3743db5909508`. The save/retirement slice is closed
by its separately committed [verification](../u02-oauth-retirement-20261016/verification.json).
The older execution receipt, inventory status and seed ledger in this directory
remain historical evidence; their statements that cross-process CAS/config ABA
are unresolved predate that U02 commit. They must not override its scoped result.
Whole-unit U02 and the complete adoption campaign remain open.

The new [parent inventory tool](tools/parent_diff_inventory.py) preserves every
commit-parent edge, including empty merge-parent diffs and unrelated root
commits. Git path bytes are authoritative base64 fields, with nullable strict
UTF-8 display fields. Raw output retains before/after object IDs and modes.
Exact blob moves, inverse deltas and repeated deltas are review candidates.
They do not prove a semantic rename, revert, reapplication or acceptance.
Every enumerated commit stays UNASSESSED and UNREVIEWED.

The frozen stable range contains 22,565 commits, 23,218 parent edges, 83 empty
parent edges and 17,398 first-parent commits. The independently frozen
supplemental range contains 22,637 commits, 23,287 edges, 82 empty edges and
17,495 first-parent commits. The ranges share 22,554 commits; 11 occur only in
the release range and 83 only in the supplemental range. Supplemental changes
are not automatically stable-release requirements. Exact inputs, output
digests and triage counts are in [the checkpoint receipt](V03_PARENT_INVENTORY.json).

The tool reuses the existing frozen-metadata helper's Git environment and input
validators. It rejects shallow/wrong-tree inputs, nonempty output directories,
and output inside the reference repository. It neither updates refs nor
checks out source. Native bare-repository fixtures exercise byte-unsafe names,
empty merge parents, root commits, inverse/reapply sequences and refusal paths.
The new 14 cases plus the older helper's 16 cases passed on Windows Python
3.12.13. Earlier RED and failed intermediate runs remain in private evidence.

The HTTP audit found that the existing downstream lock already includes MCP
2.0.0 and httpx2/httpcore2 2.12.0. Their wheel records match the fixed release.
No dependency was installed, upgraded or removed. Ten named installed packages,
covering 272 module/data files, were compared byte-for-byte with wheel archives
downloaded from the current lock; archive size and SHA-256 were checked before
opening them. Nine wheel records also match the fixed release. The exception
is idna: local 3.18 versus release 3.19. That difference is still unassessed.
This is a named HTTP/SDK slice, not a proof of the entire dependency closure.
The optional HTTP/2 stack is not installed and has not been tested.

The existing native redirect/header suite initially refused all six cases at
its historical U02 source-hash guard. Only two product-source hashes and an
explanatory comment were updated to the independently approved U02 commit.
External SDK hashes and every functional wire assertion remain unchanged.
The rerun passed all six cases using the real SDK and owned loopback peers,
including foreign redirect/header exclusion, compatibility, proactive refresh
and a 401 retry. Product/test source hashes matched before and after the run.
This does not qualify remote providers, TLS recovery, sleep/resume or a soak.

Reproduction uses the existing native virtual environment, an isolated
HERMES_HOME/TEMP/TMP, disabled automatic pytest plugins and no paid provider.
Raw large inventories, XML, traffic evidence, artifacts and intermediate
failures remain under `tmp/probes/v03-20261016/`; they are not staged. Run the
tool against the reference repository with the receipt's full base/end/tree
values and a new empty output directory. Its CLI requires `--repo`, `--base`,
`--end`, `--expected-tree` and `--output`. Run the two tool test files with
`python -B -m pytest -p pytest_asyncio.plugin -o addopts=` and a fresh private
`--basetemp`. No live profile or service is needed.

The receipt records CodeGraph and independent review for the exact source.
V03 semantic classification and V04 full dependency acceptance are still open.
The original 18 units, five retained slices, remaining native/E2E gates,
eight-hour soak, three actual sleep/resume cycles and release qualification
must not be inferred from this checkpoint. No push, PR, main integration,
version bump, release, deployment or production runtime change is authorized
or claimed. Existing unrelated WIP and the protected primary are retained.
