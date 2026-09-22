# Instructions for agents changing or integrating this component

Read `docs/implementation-router/AGENT_PROTOCOL.md` and `STATUS.md` first.
Keep credentials in the parent Hermes harness. Never satisfy the admission
contract by fabricating a receipt in a plugin or prompt. Do not instantiate
credential-bearing child AIAgents to make the demo work. Missing secure native
integration is a blocker, not permission to bypass it.

Use explicit operator-owned routes, not hardcoded model names or fallback as
an escalation mechanism. Preserve core approval, lifecycle, tool and provider
authorities. Keep machine codes language-invariant. Run component tests,
security and lineage probes, locale parity, mutation tests, and final-head
native/full CI separately; report omissions and skips accurately. No merge
or upstream completion claim until the real native adapter is qualified.
