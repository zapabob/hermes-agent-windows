# T15 Security Center correction evidence

## Source and scope

Repository: `zapabob/hermes-agent-windows`.

Worktree: `H:\hermes-worktrees\t15-security-semantics`.

Branch: `codex/t15-security-semantics`.

Base for the T15 feature: `05889e42e0f773e2d54c64a8fd9d056e0d170df4`.

Prior T15 implementation: `9869602a084301021bd884c40d0643d6cf22aade`.

Correction commit: `95cf47dfb0aa294f8def943b8e98b6ed4f6bec9e`.

The correction is confined to the downstream security models, policy, service, execution gate, `tools/terminal_tool.py`, and focused security regression tests. No Desktop, Go, llama, or operational configuration files changed. The public scan envelope retains legacy `verdict`, `action`, and `cached` fields.

## Added regression coverage

Before the fix, the new boundedness assertions failed in four cases: forty unresolved references produced forty public results; a 3,000-character candidate path was reflected into the public result; two unresolved references produced two public results; and a public `ScanResult` path exceeded 3,000 characters.

The fix caps command analysis at 64 KiB, candidate references at 32, and one reference at 2,048 characters. Parse, count, and reference-length failures use fixed reason codes. Any unresolved candidate set produces one generic refusal with no command-supplied path. Public scan paths are capped at 256 characters. The candidate parser remains a bounded userspace check for literal recognized suffixes; shell interpolation and command substitution without such a literal remain outside its coverage.

The focused T15 suite passed after the fix:

```text
.\.venv\Scripts\python.exe -m pytest tests\security\test_t15_security_semantics.py -q
24 passed
```

The combined security and API checks passed with the two local EICAR detector assertions excluded:

```text
.\.venv\Scripts\python.exe -m pytest tests\security\test_t15_security_semantics.py tests\security\test_security_center.py tests\security\test_security_api.py -q -k 'not real_clamav_detects_eicar_when_required and not bundled_yara_core_detects_eicar'
70 passed, 2 deselected
```

The affected terminal suites passed:

```text
.\.venv\Scripts\python.exe -m pytest tests\tools\test_terminal_tool.py tests\tools\test_terminal_tool_exception_redaction.py tests\tools\test_terminal_tool_requirements.py tests\tools\test_terminal_tool_pty_fallback.py -q
26 passed
```

Ruff 0.15.10 passed on the six changed source/test files. Ty 0.0.21 passed on the changed security modules and the focused test. `git diff --check` passed. The two fixture-only detector checks were attempted separately and failed to produce the expected ClamAV and bundled YARA EICAR detections. No live malware was downloaded or executed; real scanner readiness is unresolved.

## CodeGraph post-commit status

CodeGraph 1.6.0 ran through the pinned npm shim with the explicit Node 22.23.2 runtime. The sync covered six changed files and 301 modified nodes. The committed-tree status reported 8,914 files, 190,999 nodes, and 611,449 edges, with zero pending added, modified, or removed files, zero pending references, complete state, no worktree mismatch, and no reindex recommendation. The raw JSON status is recorded in `evidence/codegraph/T15-95cf47df-after.json`.

H had 21,526,786,048 bytes free after the sync, above the 8 GiB floor. The serialized CodeGraph writer was released to the coordinator after status verification.

## Remaining integration and runtime gates

Terminal revalidation compares candidate path sets, file identity, size, and SHA-256 immediately before execution. It narrows the userspace check-to-use interval but does not pin the shell's later open; a replacement after the check returns can still race with execution.

`SecurityService.status()` avoids quarantine-vault creation, but its current ClamAV version lookup can still run `clamdscan` or `clamscan --version`. T16 owns that remaining status-read process behavior, so status is not claimed to be fully side-effect-free.

The Desktop `SecurityScanResult` projection still lacks `file_verdict`, `engine_health`, and `execution_decision`. T19 owns that UI projection gap. No real malware was used and the local fixture detector failures leave the real ClamAV/YARA runtime gate unresolved.
