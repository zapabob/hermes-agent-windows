# Windows Tier-1 CI and local inference repair

## Scope and acceptance

Continue from main `27b03caca183ea1665740e0b8e283df9b0c2bfea` without deleting
existing files, changing unrelated WIP, or changing the product version.
Repair both failed Tier-1 jobs without weakening integrity, advisory or
checkpoint checks. Validate the same published SHA in cloud CI, then restart
the canonical Hermes services and require actual chat, tool and embedding
responses. A listening port or a healthy process alone is insufficient.

## Findings and implementation

The CPU checkpoint job replaced the default index with the PyTorch CPU index.
Its transitive `filelock` dependency could not be resolved. The job now uses
uv's CPU backend selection, which scopes the PyTorch index to Torch while
ordinary dependencies use PyPI. `--no-config` isolates this separate CPU lane
from the root project's resolver configuration. Torch and the private
Accelerate version assertions, disabled CUDA, and checkpoint tests remain.
Reference: <https://docs.astral.sh/uv/guides/integration/pytorch/>.

The private wheel license is compared byte-for-byte. Windows checkout could
convert the standalone license to CRLF while leaving the wheel unchanged.
The license now explicitly checks out as LF. A real Git checkout regression
uses `core.autocrlf=true`; removing the attribute in the fixture must still
fail the existing integrity guard. Wheel bytes, hashes, frozen inputs and
license checks are unchanged.

Extending that checkout reproduction to all eight frozen input files exposed
the same conversion problem for the two JSONL datasets. Their byte identity
is now also pinned to LF. This follow-up was reproduced as `frozen input hash
mismatch` before the attribute was added, rather than bypassing the hash guard.

The live generation server has one 131072-token slot and multiple concurrent
connections from the Desktop backend. It continues generating tokens, so
transport health is distinct from request queue latency. The existing
Windows launcher gains optional `ContextPerSlot` and `ParallelSlots`
parameters. Explicit per-slot capacity allocates the corresponding total
context; omitted parameters preserve the legacy total-context behavior.
Validation rejects invalid parallel counts, undersized per-slot context and
integer overflow. The deployment candidate is two slots with 131072 tokens
each, retaining the existing GGUF, q4_0 K/V cache, Flash Attention, speculative
ngram decoding and tool templates. Live capacity and response proof remain
deployment gates, rather than assumptions from arithmetic.

## Preservation and verification

Work occurs in the existing isolated integration worktree. Primary main was
clean at entry. The nine dirty/untracked WIP files in the protected source
worktree were hashed before edits. No reset, clean, broad stage, or cache
deletion is used. Existing environments are not synchronized through their
junctions. Local tests use `uv run --no-sync` with the existing Python 3.12
environment; root metadata accepts Python 3.11 through 3.13, while uv also
reports the checkout's preferred Python 3.11. Cloud lanes retain their own
selected interpreters.

Focused verification: 31 tests passed, including the actual PowerShell
allocation function, invalid input paths, Git line-ending conversion, pilot
integrity and downstream CI contracts. Ruff passed for both changed Python
tests. The first allocation harness run had a PowerShell syntax error in the
new test itself; that run is not claimed as a semantic RED. The corrected
native test and fail-closed checkout fixture provide the regression evidence.

An additional fresh CPU-only installation with the CI-pinned uv 0.9.28
resolved Torch's dependencies but failed while extracting its wheel because
the local disk filled. No files or caches were deleted. CPU environment
creation must therefore pass on the cloud Windows runner before completion.
Real CodeGraph 1.5.0 provides source-bound navigation; PowerShell behavior is
verified with the native parser and execution, not claimed as graph coverage.

## Process and remaining gates

Applied the common engineering, implementation start, skill selection,
security, deep research, LLMOps, application, network and Python SOPs. Skills:
`milspec-codex-standard`, `gh-fix-ci`, `deepresearch-defense-standard`,
`code-review-and-quality`, and the Windows Hermes runtime restart skill.
The direct user request authorizes implementation, main publication and
runtime restart; no additional PR workflow or reviewer messaging is needed.
An independent local review is required before integration.

Independent review completed on these five implementation/test files with no
actionable findings. It explicitly leaves cloud CPU installation and live
two-slot responses as separate gates. Windows footgun scan (1528 files),
downstream policy validation, private wheel/source and frozen-input integrity,
and `git diff --check` passed locally.

The first commit invoked the pre-existing broken Lefthook bootstrap, whose
fallback `uv run lefthook -h` recreated the junction-shared WIP environment
with Python 3.11 before the call was stopped. This was an execution mistake;
the previously known bootstrap failure should have been isolated before the
commit. WIP source-file hashes remained unchanged and the separate canonical
production environment was unaffected. Recovery preserves the partial
replacement and copies the known canonical Python 3.12 environment to a new
isolated location with sufficient capacity. The original pre-hook environment
cannot be claimed byte-identical. Subsequent Git operations use the hook's
process-local `LEFTHOOK=0` guard; no global hooks/configuration are changed.
Explicit lint, native tests, policy and cloud gates remain required.

Recovery verification: the WIP environment now has an independent Python
3.12.13 copy of the canonical dependency baseline, a regenerated editable
package pointing at the protected source checkout, verified core imports,
and 31 passing focused regressions. All nine protected WIP source hashes
remain unchanged. `uv pip check` reports one mismatch with that older source
manifest: it pins cryptography 50.0.0, while the canonical recovery baseline
retains 50.0.2. No protected manifest was edited and no security dependency
was downgraded. This functional recovery does not establish byte identity
with the environment that the hook replaced.

## Full-CI follow-up and runtime results

The eight candidate Tier-1 jobs passed at `08fe9964604`. Its main run hit
Chocolatey's HTTP 503 during ClamAV installation; the failed job was rerun
without omitting antivirus qualification and the workflow then succeeded.
Nix, Docker and Windows runtime authority also succeeded at that SHA.

The broader Windows-only suite exposed a pre-existing WhatsApp test isolation
race: patching `adapter.subprocess.run` replaced the shared standard-library
function, so a background cleanup worker's separate `taskkill` polluted the
mock call count. The test now injects only the adapter module's subprocess
and asyncio dependencies. The exact one-call bridge-tree assertion remains.
An unrelated, harmless, hidden Python child is started inside the scope:
the original global mock deterministically fails with two calls, while the
isolated mock permits that real child and still requires exactly one bridge
termination. Production WhatsApp behavior is unchanged. Native file result:
11 passed and one POSIX-only test skipped. The focused regression also passed
with RuntimeWarning treated as an error. Whole-file execution emitted an
existing unawaited-AsyncMock warning during GC; it is not reported as a clean
warning-free suite. Ruff and whitespace checks passed.

The full Hermes fleet was restarted without force-killing gateways. Both
generation slots reported 131072-token capacity and speculative decoding;
the model, q4_0 cache flags and existing decoding/template options were
retained. After pending cold long-context work completed, two simultaneous
short requests returned final content in 16.438 and 16.203 seconds with the
same 45-second probe deadline that failed before. A structured tool call
returned in 1.765 seconds, and embedding returned 1024 finite nonzero values.
One real isolated Hermes conversation completed in 13.594 seconds. An earlier
post-restart probe still timed out while a resumed 58K-token prompt occupied
the server; these results do not guarantee bounded latency when both slots
are occupied by long work. No prompt cache, tool or reasoning capability was
removed to obtain the warm response results. The separate Hikari re-launch
script was backed up and given the same verified two-slot capacity.

## Security Center progress-output follow-up

The reported screenshot was traced to the read-only feed record: freshclam
exited zero but `output_truncated` was true. Repeated download progress
redraws exhausted the 16 KiB bounded capture, so activation was correctly
refused under the existing incomplete-output policy. Successful bytecode
download alone did not establish an activated feed.

Pass freshclam's supported `--quiet` option to suppress routine progress and
retain error messages. Do not raise the output cap, ignore truncation, change
signature verification, or mark a failed update successful. The subsequent
bounded inventory, sigtool checks, activation and post-activation identity
verification remain unchanged. The installed 1.5.4 executable's help confirms
the option; official usage documents scripted quiet updates at
https://docs.clamav.net/manual/Usage/Configuration.html#freshclamconf.

The new regression runs a harmless real child through the production bounded
process helper. Before the fix, a zero-exit progress flood failed to activate;
afterward it activates and preserves the preceding definitions. Nonzero exit,
overflow even in quiet mode, and malformed definitions still fail and retain
the existing active definitions. Native Windows combined result: 98 passed,
four platform skips. Ruff passed. Real CodeGraph bound the updater/service/
validation slice before editing; independent review and the final pushed-SHA
workflows remain separate completion gates. Live definition rotation must
first preserve the pre-existing previous directory under a unique backup
name; do not let rotation erase retained user files.

Independent read-only review found no actionable issue in the updater and
new regression. The existing center suite initially exposed missing optional
YARA in the recovered test environment. Installing the already-locked
yara-python 4.5.4 Windows wheel with its uv.lock SHA-256 into that isolated
environment produced 39 passing center/progress tests and one platform skip.
The production environment was not changed by that test dependency install.
The freshclam regression is included in the Windows-native CI lane.

At this implementation commit, cloud validation and runtime deployment are
pending. Keep private machine receipts outside the repository. Completion
requires terminal-success workflows on the final main SHA, preserved WIP
hashes, visible responsive Desktop, Electron-owned backend agreement with Go,
four current-version gateways, server health, final chat content, structured
tool calls and finite nonzero embeddings. Preserve exact gateway/channel
failures separately from process restart status. Rollback uses retained old
model arguments and the prior Git commit; do not delete model or user data.
