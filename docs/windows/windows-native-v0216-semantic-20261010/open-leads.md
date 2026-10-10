# Additional inventory leads

These entries are source risks or bounded observations, not completed fixes. They augment the seed inventory and must receive source-bound disposition and behavioral qualification.

## B07: steering cancellation after a consumer takes the note

agent/agent_runtime_helpers.py apply_pending_steer_to_tool_results and agent/conversation_loop.py pre-API steering temporarily drain a note, then restore it if no tool target is available. A Stop that occurs after the take is outside a later buffer discard. Establish deterministic take/Stop/restore and take/Stop/inject oracles before deciding whether cancellation should win; preserve markers already delivered before Stop and do not rewrite cached historical context. Review shared AIAgent hard-stop semantics and all local/compute-host/classic CLI/messaging owners before claiming whole-class closure.

Status: SOURCE_RISK_REQUIRES_REPRO. No implementation or final disposition.

## Security Center typed result projection

The frozen downstream ScanResult.to_dict exports file_verdict, engine_health and execution_decision. Desktop SecurityScanResult lacks these axes, and SecurityView derives engine tone from a version string and scan completion toast from result count. The existing profile/connection-scoped REST owner must be preserved. SC01/SC02 require actual UI reproduction, typed transport contracts, positive/negative policy projection and control-panel acceptance before implementation closure. Existing records of scanner/vault tests are historical evidence, not current native qualification.

Status: source discrepancy confirmed; UI effect and runtime acceptance remain open.

## B08: retained ConPTY handle after bridge close

Task-owned native transport calibration observed real input/Enter/output, then WinPtyBridge.close terminated the Python child while the retained bridge/pywinpty object still kept its headless conhost alive. The recorded PID, creation time, executable and argv were verified before recovering that exact calibration survivor. A separate calibration that explicitly closed the pywinpty connection and released the retained fixture handle exited all recorded descendants. Both runs and the identity-checked recovery are preserved locally.

This proves the bounded retained-fixture behavior, not a leak in the public dashboard lifecycle. Trace the real /api/pty bridge owner and its reference lifetime, then reproduce close/disconnect/update through that public owner before proposing a product repair. F01 native fixture cleanup may release its own connection/handles but must not claim WinPtyBridge.close alone passed this oracle.

Status: NATIVE_CALIBRATION_OBSERVATION_REQUIRES_PUBLIC_OWNER_REPRO. No product implementation or final disposition.

## B09: POSIX-only CLI initialization assertions executed on Windows

F01's related-owner regression run observed two failures in tests/cli/test_cli_init.py: test_lf_enter_binding_respects_multiline_shortcuts expected a POSIX legacy c-j binding, and test_cpr_gating_posix_suppresses_without_ssh expected POSIX CPR suppression. A clean isolated worktree at D_BASE 606f7e557c13a0789a2420f7adf6181becf60d75 reproduced exactly the same two node failures, with 35 other tests passing. The test docstrings describe POSIX coverage and refer to separate native Windows cases, but the two methods lack linux_only/platform gating. Windows leaves c-j available for its newline handler and its normal CPR result is False.

This is a reproduced fixed-base test applicability defect, not a F01 queue regression. Preserve the full failed runs. Add correctly scoped POSIX markers in a separately reviewed change, retain and execute the native Windows counterpart tests, and verify the Windows runner's skip/selection semantics before claiming closure. No platform identity mocking or weakening of the Windows expectation is authorized by this observation.

The candidate adds only two existing skipif decorators. Native per-file JUnit records retain all 41 collected nodes: 37 PASS and four expected POSIX SKIPPED, including the two corrected methods and three explicit native Windows counterpart passes. Product owners and every assertion remain unchanged. See B09-mini-plan.md and B09-receipt.json for exact qualification.

Status: IMPLEMENTED_AWAITING_INDEPENDENT_B09_ACCEPTANCE. Linux/macOS execution and cloud CI remain separate unqualified gates.
