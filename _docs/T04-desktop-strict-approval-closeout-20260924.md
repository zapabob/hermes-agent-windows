# T04 Desktop strict approval review

Desktop keeps the strict control approval binding from the gateway event through reconnect replay. The pending prompt retains the operation digest, resource URI, and grant revision so the user can review the exact request.

The approval card shows the full resource and grant revision before Run. An incomplete strict binding disables Run, and a stale button handler cannot resolve a replacement request. The native notification offers no approval action for strict requests; Reject remains available, and the notification handler rejects any strict approve action that reaches it.

The regression fixtures use reserved HTTPS URLs under `mcp.example.test`; a long operation path verifies the resource remains fully visible in the review card.

The approval response stays owner-routed through `control_approval.respond` with the request ID and intent digest. Ordinary approvals continue through `approval.respond`.

Focused verification: four Desktop Vitest files, 74 tests. Typecheck, lint, production build, and CodeGraph after-change evidence are recorded with this task's commit.

Manual qualification remains open for rendered Electron layout, live client authentication/transport, and a real approved operation. The focused tests exercise the renderer/store boundary in Vitest and do not claim those live paths.
