# T04 Code and Security Review — 20565df10d

## Scope and method

Reviewed commit `20565df10d51573f327b36790f3eea5f1755db58` against its parent. Scope was the T04 diff plus its immediate approval/authentication/dispatch path: `tools/approval.py`, `downstream/control_mcp/{journal,coordinator,auth}.py`, `tui_gateway/methods_prompt.py`, `tui_gateway/server.py`, and Desktop approval ingestion/rendering.

The requested `omo ulw-loop status --json` command was unavailable (`omo` was not on PATH), so this report uses the required fallback path. The supplied T04 evidence was treated as untrusted and checked against the committed tests and source. No services were started and no production files were changed.

## Skill-perspective check

The reviewer could not locate the optional `remove-ai-slops` and `programming` skills in the local skill catalog, so it applied the review criteria stated in the task instead.

The changed Python tests are not deletion-only, tautological, or simple implementation-constant mirrors: they exercise mismatched resource/grant bindings, old ACK behaviour, and second consumption. The production diff does not add unnecessary parsing or abstraction. The diff does violate the programming perspective at the Desktop boundary because the new security-relevant fields are discarded rather than represented and rendered as typed approval data.

## Findings

### CRITICAL

None.

### HIGH

1. **The Desktop human approval surface discards the new resource and grant-revision fields, so the claimed binding is not reliably visible before approval.**

   `tools/approval.py:3088-3095` correctly sends `control.resource` and `control.grant_revision`. `tui_gateway/server.py:2827-2845` forwards the control payload. However, `apps/desktop/src/store/prompts.ts:77-100` defines and parses control data as only `operationId` and `intentDigest`; `apps/desktop/src/app/session/hooks/use-message-stream/gateway-event/input-requests.ts:246-257` stores only that reduced object. The Desktop renderer never renders a resource or grant revision field. Its fallback shows the free-form description only in a `truncate` span at `apps/desktop/src/components/assistant-ui/tool/approval.tsx:77-95`, and the Run button remains immediately available at `apps/desktop/src/components/assistant-ui/tool/approval.tsx:137-146`.

   The journal places the binding values inside the description at `downstream/control_mcp/journal.py:193-207`, but `ControlApprovalBinding` permits a resource up to 2,048 characters and a description up to 6,144 characters (`tools/approval.py:3058-3069`). For an allowed long resource, the grant revision can be outside the visible truncated text; there is no resource/grant-specific expansion or confirmation. Therefore a human can approve a request without seeing the exact new security binding that T04 is intended to present.

   Reproduction: configure a valid 2,048-character HTTPS resource, issue a control approval, and open the Desktop fallback. Its fixed-width truncated description hides the trailing `(grant revision N)` while Run is enabled. This is a security contract failure, not merely a presentation concern.

   Required correction: carry `resource` and `grant_revision` through the typed Desktop `ApprovalRequest` control object and render both as non-truncated, reviewable fields in the strict approval card. Add an end-to-end Desktop event-to-RPC regression proving the visible values and strict response are tied to the same request.

### MEDIUM

1. **The new binding regression test ends at the Python notification callback and does not cover the actual trusted UI path.**

   `tests/control_mcp/test_operations.py:105-139` verifies `seen[0]`, a direct callback payload. It bypasses `tui_gateway/methods_prompt.py:1775-1806`, Desktop event ingestion, and the approval component. The only committed TUI assertion (`tests/tui_gateway/test_protocol.py:1330-1366`) builds a control dictionary that lacks both added fields. This leaves the human-surface regression untested and allowed the HIGH issue above.

   The supplied `evidence/codegraph/T04-green-tui-approval.txt` reports two passing tests, but that result does not establish field preservation or on-screen visibility.

### LOW

None.

## Verified positive controls

- Resource and grant revision are added to the immutable `ControlApprovalBinding`, validation rejects malformed values, and the journal reconstructs the same values from the reserved row: `tools/approval.py:3045-3070`, `downstream/control_mcp/journal.py:192-214`.
- Approval consumption is one-use under `_lock`: the decision must be the same issued object, its complete binding must compare equal, and the entry is removed before returning a verdict: `tools/approval.py:3216-3234`. This covers replay and mismatched resource/grant in-process.
- The ordinary `approval.respond` route calls only `resolve_gateway_approval` (`tui_gateway/methods_prompt.py:1732-1771`), while strict approvals use `resolve_control_consent` with a request id, digest, single-use choice, and transport-bound runtime session (`tui_gateway/methods_prompt.py:1775-1806`; `tui_gateway/server.py:2997-3020`). A legacy delivery ACK only sets `acknowledged` (`tools/approval.py:3249-3256`) and cannot decide the strict entry.
- Journal access/approval/claim paths bind subject, client registration, resource, and grant revision, and the coordinator revalidates the grant before approval and dispatch: `downstream/control_mcp/journal.py:127-215,268-291`; `downstream/control_mcp/coordinator.py:25-87`; `downstream/control_mcp/auth.py:134-149`.
- Binding resource rejects ASCII control characters, so the new resource field itself does not permit newline/control-character description injection (`tools/approval.py:3058-3064`). The task text remains operator-visible free text, but this predates the T04 diff and is not an authority input.

## Test and evidence review

Locally ran, read-only:

```text
./.venv/Scripts/python.exe -m pytest tests/control_mcp/test_control_approval.py tests/control_mcp/test_operations.py tests/tui_gateway/test_protocol.py -k 'control_approval or binding or legacy_delivery_ack' -q
24 passed, 83 deselected in 6.44s
```

`git diff --check 20565df10d^ 20565df10d` passed. Committed evidence also records `189 passed, 1 skipped` for the Control MCP suite and `2 passed` for focused TUI approval checks, but neither substitutes for an actual Desktop rendering/client integration test. Actual Desktop UI operation and real MCP-client interaction were intentionally not run in this read-only review.

## Decision

- `codeQualityStatus`: **BLOCK**
- `recommendation`: **REQUEST_CHANGES**
- `blockers`:
  1. Preserve and display the exact resource and grant revision as dedicated, non-truncated fields on the Desktop strict-control approval surface before Run is actionable.
  2. Add a UI-path regression from `approval.request` payload through Desktop storage/rendering and `control_approval.respond`, covering a long valid resource, a non-default grant revision, and rejection of stale/mismatched response state.

## Follow-up review at the Desktop fix

An independent read-only review of `78c0e980d20ffda71a1205f6614be9a4e27f1109` against its predecessor found both blocking Desktop paths closed. The event parser retains the resource and grant revision; the approval card presents both before Run, with the resource scrollable instead of truncated. A stale request object and an incomplete strict binding cannot issue an approval RPC. Strict OS notifications omit Approve, and their action handler rejects an approve action even if the platform delivers one. The reviewer reported `WATCH / APPROVE` with no blocking finding. This updates the earlier BLOCK decision for that reviewed diff; it does not certify an actual rendered Electron window or a live client approval.

The reviewer identified one low-severity follow-up: two public Desktop payload type declarations still omit resource and grant revision. A separate narrow type correction is pending. On the integrated commit `d40e052476`, the four affected Desktop Vitest files were re-run: 74 passed in 67.09 seconds. The build and lint recorded in the worker receipt were run before the commit, so exact-final-HEAD and live-client gates remain open.

## Type follow-up closure

The narrow type correction is integrated at `9ef2897370`. Both the gateway event and session-resume payload declarations now carry the optional resource and grant revision fields, and the source-routing test checks those public types. The isolated T04 worktree passed its focused 5-test Vitest file before commit, and the integration branch reran that same file after the type and ledger commits: 5 passed at `b5e943d2f3`. Neither this result nor the earlier 74-test result proves rendered Electron behaviour or a live client approval. The low-severity type finding is closed at source level; the live and campaign exact-final-HEAD gates remain open.
