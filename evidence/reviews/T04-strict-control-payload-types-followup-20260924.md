# T04 strict control payload type follow-up

The T04 approval review found that two public Desktop wire declarations omitted
the `resource` and `grant_revision` members already consumed by strict approval
parsing. Both event and resume payload declarations now include those members
as optional fields, preserving compatibility with older and malformed payloads.

The source-routing regression test uses TypeScript `satisfies` checks against
both `GatewayEventPayload['control']` and
`SessionResumeResponse['pending_approval']`, so both live events and replayed
approvals must retain the complete wire shape at compile time.

Verification on 2026-09-24:

- `pnpm exec vitest run src/app/session/hooks/use-message-stream/gateway-source-routing.test.tsx`: 5 tests passed.
- `pnpm run typecheck`: passed for renderer, Electron, and E2E TypeScript projects.
- ESLint on the two declarations and source-routing test: passed.
- CodeGraph reported three pending source changes before sync, then synced three
  files (270 nodes); queries resolved `GatewayEventPayload` and Desktop
  `SessionResumeResponse`, and final status reported the index up to date.
- `git diff --check`: passed.

No gateway service, remote client, or rendered Electron session was run. This
follow-up changes only the Desktop payload declarations and their type-tested
fixture; the existing approval behavior is unchanged.
