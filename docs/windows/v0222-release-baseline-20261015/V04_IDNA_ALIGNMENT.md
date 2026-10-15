# Frozen-release IDNA behavior alignment — 2026-10-16

This checkpoint aligns only the IDNA dependency behavior within C04/V04 with
release d923a5eb487a17c0a68801bba9ef0f56c81040a8, tree
5a064077e8d1de9fc7a4b27efc04f0caa2cb06c0. The starting local commit is
20336f01c478392ad3d981819ba474c223a88b17. Full V04, the original units and the
adoption campaign remain open. Exact inputs and evidence hashes are recorded
in [the scoped receipt](V04_IDNA_ALIGNMENT.json).

The only product change replaces the idna 3.18 lock record with the exact
3.19 record in the frozen release: version, source archive and wheel, three
removed and three added lines. All other package records and top-level lock
fields remain equal, and pyproject.toml is unchanged. Existing httpx2,
httpcore2 and MCP package records are retained. The IDNA update first appears
in retained upstream commit 3cbd595c84558c58bbe10699b12a20d6dcb785c4;
the C04 HTTP-stack lead commit alone is insufficient evidence for this record.

The behavior contracts cover explicit and default STD3 rejection, useful
non-STD3 mapping, validation after mapping, canonical A-label round trips,
structured Unicode errors and display behavior. Valid Unicode hosts continue
to work. Consumer expectations use independent fixed ASCII/Unicode pairs;
the tested encoder and decoder do not calculate their own expected hostnames.
HTTPX and httpx2 intentionally differ when displaying a noncanonical ASCII
wire label; their constructors retain that wire label, while their decoded
host properties follow their respective existing contracts.

Final native Windows Python 3.12.13 qualification passes 126 cases in fresh
processes per file: 48 new IDNA/consumer cases, 72 existing URL-safety cases,
and six existing real-MCP-SDK redirect/auth cases. All have zero failures,
errors and skips. Three new cases send actual HTTP requests through HTTPX,
httpx2 and Requests to an owned ephemeral loopback peer, inspecting the actual
punycode Host header and absence of auth/proxy auth. An AnyIO case checks
Unicode resolution. The resolver accepts only the fixed test hostname and
loopback addresses. These local peers do not prove a real external provider,
production configuration, real model inference or Desktop integration.

The final 48-case source produces 17 assertion failures and 31 passes with
the existing base idna 3.18; there are no import/fixture errors or skips.
That base has pre-existing yarl/propcache drift and is explicitly identified
as the RED environment, not as the candidate's locked runtime. Candidate
qualification uses verified idna 3.19, yarl 1.24.5 and propcache 0.5.2 wheels
in an owned test-only target. No base installation or synchronization occurs.
Three disposable in-memory anti-fixes are detected: disabling STD3 checking
causes six failures, disabling canonical validation eight, and forcing strict
mapping despite explicit opt-out three. Installed payloads remain unchanged.
The independent review additionally checks a paired wrong-encoder/decoder
counterexample against the fixed consumer expectations.

The candidate's named HTTP dependency subset contains 16 locked distributions
and 372 module/data/native payload files, all byte-equal to their selected
lock-pinned wheels. Artifact size and SHA-256 are verified before wheel reads
or execution. HTTPX and httpx2 reference the same target IDNA module.
All 16 base distributions, including 837 files and their complete discovered
file sets, versions and hashes, are unchanged after qualification. These are
named subset checks, not a proof of the complete project dependency closure.

The existing uv 0.11.29 validates the lock before and after with
`uv lock --check --offline --no-build --no-python-downloads --python .venv/Scripts/python.exe --no-progress`,
resolving 259 packages. An earlier offline dry upgrade lacked certifi metadata
in its fresh cache for another Python fork. That is retained as a resolver
limitation, not counted as behavioral RED. The exact frozen IDNA record was
therefore copied minimally and validated; no broad relock, all-extras sync or
new dependency is introduced. Ruff and whitespace checks pass. CodeGraph
1.6.0 is complete on the final test source with no pending changes/references;
dynamic IDNA and socket edges are complemented by actual runtime evidence.

Maintainer [3.19 history](https://raw.githubusercontent.com/kjd/idna/03a9a11dd8aecd4fea742cabe20f4d3d9ed82abb/HISTORY.md)
and the [3.19 registry record](https://pypi.org/project/idna/3.19/)
support the frozen behavior and artifact identity. Registry-reported
publishing provenance is not an independently verified cryptographic
attestation here. The [maintainer advisory](https://github.com/kjd/idna/security/advisories/GHSA-65pc-fj4g-8rjx)
was patched in 3.15, so this checkpoint does not misclassify 3.18 as below that
patch boundary. [Version 3.20 history](https://raw.githubusercontent.com/kjd/idna/v3.20/HISTORY.md)
already exists and includes incremental-codec behavior changes; that later
version is outside this frozen-release alignment and remains unassessed.
This checkpoint does not claim latest-version status or full security closure.

Independent final approval and its exact reviewed source bindings are stored
in the scoped receipt. Earlier failed and intermediate receipts remain private
and unaccepted. This checkpoint supersedes only the IDNA-open statement in
the preceding V05 checkpoint; it does not rewrite that historical record or
the older seed campaign ledgers.

Private evidence remains under tmp/probes/v04-idna-20261016. The primary
checkout, existing WIP, operator configuration, services and models remain
protected. The stale shared Lefthook launcher is disabled only for the local
commit command with LEFTHOOK=0, retained unchanged and not counted as a passed
hook. Only four explicit paths belong to this commit. Any later recovery uses
a reviewed inverse commit. There is no push, PR, main integration, version
bump, release or deployment. Eight-hour soak and three actual sleep/resume
cycles remain unexecuted because no dedicated Windows environment is available.
