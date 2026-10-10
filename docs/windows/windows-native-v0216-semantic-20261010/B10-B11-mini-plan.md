# B10/B11: native Windows command transport and owned cancellation

Integration parent: 34254176282b61d1c4ed8ff4cd20b1a8a8f59ed6. Fixed release/reference/base inputs remain those in README.md. This additional discovery slice implements the authorized local campaign; it does not accept all W02, background process owners, or release compatibility.

## Source and credit

B10 extends the immutable child-credential policy added by human contributor 峯岸 亮 in 989b0709c3f0ae6ff4493ebd24e4fa82bbbdb9ac. It preserves validated snapshot authority, pinned per-spawn bytes, monotonically accumulated protected names and profile isolation. The legitimate command transport changes; the protection remains mandatory.

B11 adopts the guarded Windows stop contract introduced by human contributor burak33bb in ed6d5fc803a1c0adc4aaf386e9d80c123fef6d8e. U_RELEASE and R_AFTER obtain creation identity again at kill time. This fork intentionally captures it at spawn and supplies that saved identity to the existing guard. A missing or mismatched identity refuses PID-tree authority and permits only the original process handle fallback. Native negative cases prove that no taskkill is called on those refusal paths. This is an intentional safety policy difference with a supported legitimate cancellation path, not unconditional acceptance of every upstream stop change.

## Observed failures and required effects

Before implementation, seven native behavioral assertions failed and the small command control passed. Under synthetic credential exclusion growth, short true/echo/date/cd requests assembled 156,717–156,720 UTF-16 units and were refused before any child effect. These are attempted invocation measurements, not captured child argv or proof of the production collection's growth source.

Further native RED established two descendant survivors after timeout/interrupt, a large login-initialization failure, and live stdin recovery/writer-start failures. Each run, exact owned process recovery and original source binding is retained. The large login script passed bash -n as a file while inline login execution failed; the launcher mechanism is unconfirmed. A 4,096-unit conservative transport-selection budget addresses that measured effect. It is not described as an operating-system command-line limit. The final 30,000-unit refusal remains separately tested.

The required success contract is real command effect once, complete payload bytes, unchanged parsing context, caller stdin fidelity, exit status, cwd and ordinary snapshot state, credential exclusion, login initialization, safe process-tree stop, and terminal-only resource cleanup. Unexpected live failures retain their owned inputs and expose the original process for explicit recovery.

## Owners and implementation boundary

The only product owner changed is tools/environments/local.py. Actual callers are BaseEnvironment.execute/_wrap_command, LocalEnvironment._run_bash/_wait_for_process and the existing terminal_tool foreground dispatch. Existing credential policy, process identity guard, BaseEnvironment wait/pipe implementation and process_registry remain unchanged.

On Windows, complete subprocess.list2cmdline UTF-16 length selects file transport at 4,096 units after login prelude assembly. The operation creates one unique owned binary UTF-8 file and writes the original bytes without newline conversion. A short Bash command uses builtin read into a nonexported reserved variable, then builtin eval with the variable unset before the payload runs. Caller stdin remains available. This preserves top-level return, BASH_SOURCE, $0 and RETURN trap behavior; sourcing the file would change those contracts. Embedded NUL remains invalid. A missing payload refuses with status 126, without executing an effect or retrying different semantics.

The final invocation still refuses at 30,000 UTF-16 units. Creation/write/guard/Popen failures remove only that operation's file. After Popen, ownership attaches before creation-identity capture or stdin setup. Live wait errors retain snapshot and command inputs. Terminal waits remove them; stdin setup errors stop/reap through the same owner or leave the original process attached for recovery. An unstarted stdin writer is detached only when its identity proves it never started; an already started writer retains the normal join contract.

Windows stop supplies the saved creation time to existing gateway.status.terminate_pid. Original-handle fallback is bounded to that handle. POSIX process-group behavior and distinct native local-background dispatch are outside this product change.

## Oracles and source controls

The committed 30-case Windows suite uses real Git Bash and real owned processes. Synthetic exclusion names contain no user credentials. Native cases cover four short commands, exact stdin including CRLF/Japanese, complete Unicode/quoted payload bytes, exit/cwd/snapshot persistence, bounded/large return and eval context, concurrent held children and failure recovery, login initialization, timeout/interrupt with a subsequent successful command, missing payload, UTF-16 budget boundaries, missing/changed process identity and writer-start lifecycle. The overlong final-executable argument is an injected guard seam, explicitly distinct from native long executable-path qualification.

The existing accumulated-wrapper refusal test now requires real successful execution and absence of protected names. All its other immutable authority, late registration, publication and profile isolation assertions remain unchanged. Four unrelated F02 RED files remain outside this change.

The public tools.terminal_tool.terminal_tool entry also runs the four short commands against its actual cached LocalEnvironment, through the real preflight and danger checks, without force, background or policy bypass. Each writes one owned marker; a protected-name probe produces empty output. This local public-entry evidence does not represent Desktop/provider/production E2E.

## Mutation acceptance

Fourteen semantic mutations target late transport selection, acknowledgement-only execution, truncation, source-context substitution, stdin corruption, missing command cleanup, premature live-input cleanup, missing/reacquired stop identity, removed identity guard, leaked recovery stdin, retained unstarted writer, discarded started writer, and removed final argv guard.

For every mutation, the same selected cases must pass before, fail with behavioral AssertionError only under the mutation, then pass after exact-byte restoration. Real CodeGraph sync records mutant and restored sources. Full 30-case before/after success, immutable integration source identity, exact restoration and independent review are required before local acceptance. The first controller's JUnit type assumption was invalid; its raw outcomes remain excluded from final acceptance. The corrected controller extracts the actual terminal failure type and preserves every run.

## Related regressions and honest limits

The broader 16-file owner run recorded 345 PASS, 10 FAIL and 14 SKIP. A fixed D_BASE control reproduced nine failures with 89 PASS and two SKIP. The remaining failure uses unguarded POSIX os.getpgid on Windows; its source is unchanged, but a D_BASE rerun for that node is not claimed. The new native timeout/interrupt cases establish this slice's actual Windows stop effects.

A later stdin/credential/MSYS run recorded 68 PASS, five FAIL and four SKIP. Its five direct bare-bash fixture failures reproduce at fixed D_BASE with 11 PASS/five FAIL. Their executable-resolution cause remains unverified. None of these failed tests was weakened or skipped. These outcomes are retained as additional Windows qualification work, not reported as an all-green owner suite.

Real CodeGraph resolves the spawn and stop owners/callers but returns no callers for the dynamic wait override. Manual BaseEnvironment source tracing and native lifecycle cases supply that missing edge; graph emptiness is not evidence of absence. No POSIX execution, packaged release, production restart, cloud CI, scheduled-task durability or complete compatibility acceptance is claimed here.

## Closure and rollback

Final qualification requires source/test hashes, per-case JUnit outcomes, all mutation receipts, public-entry evidence, final Ruff, fresh graph with verified retained bytes, unchanged F02/locks/shared owners, protected primary HEAD/status/23 hashes, independent final review, and exact staged/local-commit blob identity. B10-B11-receipt.json records the completed gates and any remaining limits.

Use a reviewed revert of the logical local commit in this isolated branch for rollback. No reset, primary checkout replacement, profile restoration, production restart or remote write is part of this slice.
