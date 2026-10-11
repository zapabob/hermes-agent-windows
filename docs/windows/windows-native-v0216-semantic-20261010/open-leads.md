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

Status: ACCEPTED_B09_LOCAL_COMMIT_IDENTITY_VERIFIED. Linux/macOS execution and cloud CI remain separate unqualified gates.

B09 product commit: 1a8f669d4e39440d1b41de6720ddce966e4d4aa9; tree: 3fa69f9a463aea6eb2ca72cac4011873d32da2d8; patch SHA256: b76ffea35f438dc80921450557f41a5d344f6370de2f3d241252cba74200a9dd. Independent review and postcommit blob checks passed; protected primary HEAD/status/23 hashes match the campaign baseline.

## B10/B11: command transport and foreground cancellation

Native RED reproduced short-command argv refusal under synthetic exclusion growth and owned descendant survivors on timeout/interrupt. The candidate preserves credential authority, uses complete owned UTF-8 command transport with unchanged caller stdin/eval context, captures creation identity at spawn, and retains live input ownership for recovery. The public terminal entry succeeds for four short commands without policy bypass. B10-B11-mini-plan.md and its receipt define the precise slice; independent final evidence acceptance and local commit identity are required before closure.

Status: ACCEPTED_B10_B11_LOCAL_COMMIT_IDENTITY_VERIFIED. This does not accept all W02 or separate process_registry/background stop owners. U_RELEASE's additional LocalEnvironment._force_kill_process override remains an unqualified compatibility lead.

## B12: related native Windows test applicability and bare-bash fixtures

The B10/B11 16-file regression run has ten failures. Nine reproduce at fixed D_BASE; one unchanged test reaches POSIX os.getpgid on Windows, with its D_BASE rerun still unperformed. Another stdin fixture suite has five bare-bash failures reproduced at fixed D_BASE. Exact executable-resolution cause is unverified. Retain the raw logs and assertions; native effect tests for the affected supported Windows contracts must accompany any later applicability correction.

Status: BASELINE_FAILURES_AND_SOURCE_APPLICABILITY_LEADS_OPEN. No weakening/skipping or whole-suite GREEN acceptance occurred.

B10/B11 product commit: 2858b4708956b4e4b57452bf796db6fd0581b792; tree: 1557cce400e3d2d6c66ac47445ccc09a0edbf9c2; patch SHA256: 866244e238436cf80c8f51b2907b0530194e4fe7495f849fc6d68fe764c8c732. Independent review, exact local blob identity and protected primary audit passed. B12 and separate force-kill/background/W02 leads remain open.

## F02: accepted local branch lifecycle and reply scope

F02 product commit: d7fc8a859e9be6117997914a6a81a7f1c45d7225; tree: 9898617817e6c546efc141ae4429231404d559f4; patch SHA256: f5657d1574c15083a033de45a42714e0931a4abb617807309e30029914808e59. The bounded receipt accepts selected CLI/API/TUI lifecycle, authenticated Gateway/Relay destinations and reply streams. Fifteen qualified/restored mutations, 66 selected files with 669 deduplicated passing cases, native ConPTY branch/resume nonempty sidecars and authenticated loopback WebSocket effects passed independent review. Exact committed blob identity and protected primary HEAD/status/23 hashes match.

Status: ACCEPTED_F02_LOCAL_COMMIT_IDENTITY_VERIFIED. Native model tool execution, Relay media/typing/task-card owners, production connectors, packaged Desktop, B07/B08/B12 and all remaining campaign/compatibility families remain open.

## B13: native Windows agent package fixtures

M02's six-file plugin caller regression run recorded 137 passes and two failures in tests/hermes_cli/test_agent_plugins.py. test_loads_manifest_skill_and_stdio_server expects uniform Windows backslashes although the unchanged `${PLUGIN_ROOT}/server.py` expansion retains mixed separators. test_symlink_escape_is_isolated_to_component fails creating a symlink with WinError 1314 on this PC. An isolated D_BASE control reproduced both failures with the same 38 other cases passing. The agent_plugins.py and test_agent_plugins.py Git blobs are unchanged from D_BASE. Command evidence is retained as m02-plugin-caller-regressions-v1 and m02-agent-package-fixed-base-control-v1 under the owned probe evidence folder.

Status: FIXED_BASE_WINDOWS_FIXTURE_FAILURES_OPEN. No test assertion, marker, dependency, privilege or product owner was changed. Platform applicability, canonical path comparison and the privilege-independent escape oracle require a separately qualified disposition.

## M06: separate Desktop MCP activation actions

M02 removes automatic reload from McpTab settings persistence, OAuth success and catalog installation. The existing setup card, connect suggestion and repair suggestion still send confirm:true to reload.mcp after their activation actions. Their effects are separate from settings saves. Inspect the user-visible consent and cached-prefix behavior through their actual owners before claiming those activation actions satisfy the explicit reload contract. Their presence is not proof of a vulnerability or authorization bypass, and M02's settings tests do not qualify them.

Status: SOURCE_BOUND_ACTIVATION_CONSENT_AND_CACHE_DISPOSITION_OPEN. Owners are apps/desktop/src/components/assistant-ui/mcp-setup-tool.tsx, apps/desktop/src/store/suggestion-providers/mcp.ts and apps/desktop/src/store/suggestion-providers/repair.ts. Runtime behavior remains unchanged in this slice; comments no longer equate these actions with Capabilities settings saves.

## M03: bounded issuer relay, profile authority and owned cancellation

This bounded candidate composes exact issuer fields into the actual existing SDK, profile authority checks into Gateway/REST session operations, and admission-aware cancellation into the shared flow. The Gateway session owner additionally preserves atomic pending reservation, one shared deadline and uncertain resource ownership. Canonical tests/fakes and actual dev Electron effects are qualified separately; admission worker seams, scripted inference and intercepted external browser launch retain explicit limitations. M03-mini-plan.md and the exact M03 receipt govern this slice's reviewed evidence and acceptance.

Current promoted relay15, lifecycle11 and native3 mutations require independent raw evidence qualification and known restoration before these records are prepared. Original mutation runs remain historical. Local staged/blob/commit identity remains a separate gate; the receipt must not imply it has already occurred.

Status: BOUNDED_RECEIPT_AND_LOCAL_IDENTITY_REQUIRED. This entry does not accept the entire M03 family or campaign. In-place authorization remint/revival, REST startup uncertainty and TTL resource retention, plugin OAuth/module split, M01/M04/M05/M06, complete compatibility inventory and remaining feature/security/Windows families remain required work. Actual external browser, live model inference, packaged runtime, cloud CI, production restart and scheduled-task health are unqualified.

## M03: verified bounded local product identity

M03 product commit: 9e2b69aac59e673aa448e70ebeccf60a89905b4d; tree: bdbf3ba616318d97e1db5143abad03d280fbff7b; patch SHA256: 5130d82e731f486ed37d8eef0736f46d7129a4a55d1b9de73230838c61665ba6. The independently accepted bounded slice preserves issuer propagation, caller profile/session authority and admission-aware cancellation. Actual32 committed blobs match the reviewed final bytes with exact EOF inheritance, and protected primary HEAD/status/23 hashes remain unchanged.

Original29 distinct restored mutation executions inherited through exact EOF projection, canonical57 cases, three dev Electron controls and two fresh cold children remain scoped to the bound records. In-place remint/revival, token revocation/config replacement, REST startup uncertainty/TTL retention, other MCP and campaign families remain open. Actual browser/model, packaged runtime, cloud CI, production and scheduled-task health are unqualified.

## M03: verified REST expired-flow retention

REST retention product commit: acd46a9f4a45d9d0a75e8191174262736762ee16; parent: 0ea37256069c897ff81e01f644253a00078b2ace; tree: 2262bf35d4676c03121d6d413087fb0031d82f2f; binary patch SHA256: 793b531b36404c59723d1985655802776a6639011c459bedbff2d4765d797945. The independently accepted one-line GC correction retains expired registry ownership until the actual worker completes SDK probe and scoped cleanup. Three canonical cases, 12 owner regressions, five distinct qualified mutations with six AssertionErrors, and 12 restored/control pass executions are accepted under M03-rest-retention-receipt.json. Actual four committed blobs and protected primary HEAD/status/23 item bytes match the reviewed records; M03-rest-retention-local-identity.json retains exact identity and audit hashes.

Status: ACCEPTED_M03_REST_RETENTION_LOCAL_PRODUCT_IDENTITY. This closes the bounded REST TTL retention lead. REST startup uncertainty, in-place remint/revival, revoked-token/config replacement, plugin OAuth/module split, other MCP contracts and the complete campaign inventory remain open. REST uses TestClient with synthetic signed-cookie authentication while the issuer/MCP peer uses actual loopback SDK transport. Public-network REST, external browser/model, packaged runtime, cloud CI, production and scheduled-task health remain unqualified. Full M03 and full campaign acceptance remain false.

## M03: verified REST worker startup ownership

REST startup product commit: ad97374eccfe1f8095e5b9186a36a7a75e3211ce; parent: fd9d8a39c23a353d2d66009f9a0f6a3a2c31e6b2; tree: 3b25f3f21bec21a1c8ce9a78b26e65400fe92e5a; binary patch SHA256: 8e5de6febfe22e0eccc213dc9ed4f4579e31a84ceab1a4cbc166639b842684b8. The accepted minimum REST correction returns the original error with a caller-visible reserved flow ID on worker construction/start failure and settles locally only when no worker object was acquired. Actual native allocated-before-ident and post-SDK workers retain ownership through their own cleanup; ident absence and TTL no longer imply REST completion. Four genuine original RED cases, four candidate GREEN cases, seven distinct qualified mutations, fourteen selected before/restored GREEN executions and seven owner regressions are bound by M03-rest-startup-receipt.json. Exact five committed blobs, primary HEAD/status/23 dirty-item bytes and the finite 880-entry archive roundtrip are independently qualified; M03-rest-startup-local-identity.json records actual identity and audit hashes.

Status: ACCEPTED_M03_REST_STARTUP_LOCAL_PRODUCT_IDENTITY. This closes the bounded REST public-error identity and premature completion correction. An unresolved attempted start intentionally remains reserved; automatic recovery is not introduced. Gateway worker/listener startup, caller-visible Gateway failure identity and real callback socket cleanup remain required next work. In-place remint/revival, revoked-token/config replacement, plugin OAuth/module split, other MCP contracts and the full frozen campaign inventory remain open. TestClient/synthetic-cookie REST and real owned loopback SDK transports retain their stated limits; public-network REST, external browser/model, packaged runtime, cloud CI, production and scheduled-task health are unqualified. Full M03 and full campaign acceptance remain false.

## M03: verified Gateway worker startup and captured Desktop cleanup

Gateway worker product commit: 19e32b1df18cd3360c602ba66a32abd73d8b39db; parent: c69d65f234b00eca1894aa3613a6347ea5fde490; tree: 424936c885977b91eb14df90d61977987ffc26ed; binary patch SHA256: c6704fd4244e6fe1ec4d53912113124ef0bde97dd9191fc28628944f582f7223. The independently accepted minimum correction keeps an acquired worker reserved until actual cleanup, returns the already-reserved identity in typed public error5024, and cancels through the Desktop controller's original connection/profile while preserving the same error. M03-gateway-worker-startup-local-identity.json binds the actual twelve committed blobs, independent reviews and postcommit primary audit.

Ten committed files equal reviewed raw bytes; two equal the exact existing Git LF projection: one CRLF in the native bootstrap helper and 146 in the receipt. Python AST and all compiled code objects, and decoded receipt JSON, are identical. The original raw source and evidence are preserved. This records inherited evidence equivalence, not new normalized-byte native execution. A failed stage raw-byte check is preserved as a binding refusal, not product test RED.

Thirteen affected files retain sixty-four fixed unique nodes: eighteen qualified inherited executions plus forty-six fresh qualified executions, 192 passing setup/call/teardown reports and 55 required cleanup property instances. The old profile eight raw passes remain excluded; the fresh profile eight bind two exact synthetic producers. The inherited eighteen retain their original four-suffix classifier limitation. Twelve canonical startup, nineteen Desktop unit and eight admission cases overlap that denominator. Six Python and six Desktop mutations and the two exact historical native scenarios retain the boundaries in the plan/receipt; no single sixty-four-case successful execution or broader production credential claim is made.

Protected primary HEAD and the original twenty-three item bytes are preserved. Two additional opaque untracked HTML files appeared separately; the additive baseline and pre/postcommit audits preserve all twenty-five current entries without reading their contents into the report, restoring them or claiming there were no additions. The finite 4,477-entry archive is independently qualified and excludes task HOME/temp, whole databases, installed executables and general package trees.

Status: ACCEPTED_M03_GATEWAY_WORKER_LOCAL_PRODUCT_IDENTITY. This supersedes the pending Gateway worker/public-failure-identity portion of prior leads, while leaving the separate callback listener native allocation and shutdown-before-serve_forever path open. In-place remint/revival, revoked-token/config replacement, plugin OAuth/module split, other M03 obligations and the full frozen campaign inventory remain required. Packaged runtime, external browser/provider/model, cloud CI, production restart and scheduled-task health are unqualified. Full M03 and full campaign acceptance remain false.
