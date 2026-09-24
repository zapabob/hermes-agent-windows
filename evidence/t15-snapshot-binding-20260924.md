# T15 scan snapshot binding and bounded projection evidence

## Source and scope

Repository: `zapabob/hermes-agent-windows`.

Worktree: `H:\hermes-worktrees\t15-security-semantics`.

Branch: `codex/t15-security-semantics`.

Base: `05889e42e0f773e2d54c64a8fd9d056e0d170df4`.

Prior T15 correction: `95cf47dfb0aa294f8def943b8e98b6ed4f6bec9e`.

Snapshot/finding-cap correction: `db9bede649bdaff6bf135f6ac68f43a02f3cae6f`.

The correction changes only `downstream/security/service.py`, `downstream/security/engines.py`, `downstream/security/models.py`, and `tests/security/test_t15_security_semantics.py`. It preserves the legacy public `verdict`, `action`, and `cached` envelope fields.

## Regression and implementation

The deterministic RED reproduced both review findings: when an inert test engine temporarily replaced the input with clean bytes and restored the original before the post-scan hash, the old path-based scan returned `ALLOW` instead of `BLOCK`; a 100-finding result also projected all findings without truncation metadata.

Engines now scan a suffix-preserving private snapshot copied and hashed through one opened source handle. The service checks source identity during the copy, compares the snapshot against the initial scan identity, verifies the snapshot after scanners finish, and rechecks the original before it attributes findings. The Windows snapshot directory has a protected DACL for the current owner and SYSTEM. A held Windows file handle allows read opens while denying write and delete sharing. Static content heuristics read the snapshot while retaining the original candidate path for suffix and location heuristics. A changed/unavailable snapshot returns a fixed review result with no attributed findings, cache entry, store event, quarantine, or ALLOW.

Snapshot tests assert that scanner input remains the original malicious inert fixture during the swap-and-restore attempt, snapshot writes are denied while scanning, owner/SYSTEM ACLs are present, and the snapshot directory is removed on the normal path. A separate test preserves original-path heuristics. Public scan projection now emits at most 64 findings and adds `finding_count` and `findings_truncated`.

The snapshot ACL is scoped to the current Windows owner and SYSTEM; it is not an isolation boundary against another process running as the same Windows identity. The held file handle protects the snapshot file against write/delete opens during scanning. The terminal gate remains a userspace check and does not pin the shell's later open, so the post-revalidation-to-open race remains unresolved.

## Verification

RED before the correction:

```text
swap/restore regression: ALLOW returned, expected BLOCK
finding projection regression: 100 findings exposed, truncation metadata absent
```

GREEN after the correction:

```text
.\.venv\Scripts\python.exe -m pytest tests\security\test_t15_security_semantics.py tests\security\test_security_center.py tests\security\test_security_api.py -q -k 'not real_clamav_detects_eicar_when_required and not bundled_yara_core_detects_eicar'
73 passed, 2 deselected

.\.venv\Scripts\python.exe -m pytest tests\tools\test_terminal_tool.py tests\tools\test_terminal_tool_exception_redaction.py tests\tools\test_terminal_tool_requirements.py tests\tools\test_terminal_tool_pty_fallback.py -q
26 passed
```

Ruff 0.15.10 and ty 0.0.21 passed on the changed security modules and focused test. `git diff --check` passed. Two fixture-only EICAR detector assertions were excluded because the existing local ClamAV and bundled YARA detection checks have not produced the expected detections. No live malware was downloaded or executed; real scanner readiness remains unresolved.

## CodeGraph after-index

The pinned CodeGraph 1.6.0 npm shim was invoked directly with Node 22.23.2. `TEMP`, `TMP`, and npm cache were set on H:. The sync reported four changed files and 162 modified nodes in 2.7 seconds.

Post-sync status reported 8,914 files, 191,022 nodes, and 611,507 edges. Pending added, modified, and removed files were all zero; pending references were zero; mismatch was null; state was complete; and `reindexRecommended` was false. The full JSON receipt is `evidence/codegraph/T15-db9bede6-after.json`.

H: had 25,018,380,288 bytes free after sync, above the required 8 GiB floor. The serialized writer slot was released after status verification.

## Remaining gates

`SecurityService.status()` avoids vault creation but the ClamAV version lookup can run `clamdscan` or `clamscan --version`; T16 owns that process behavior. The Desktop typed `SecurityScanResult` projection gap remains with T19. Real ClamAV/YARA runtime detection is unresolved, and the literal recognized-suffix parser cannot cover shell interpolation or command substitution that has no literal candidate.
