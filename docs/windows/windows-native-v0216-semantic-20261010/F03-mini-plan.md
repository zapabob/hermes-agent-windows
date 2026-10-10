# F03: canonical steer alias and local Desktop admission

Status: source-bound candidate independently approved for local product commit. Postcommit identity closure remains required; full campaign acceptance remains open.

## Source and owners

The upstream implementation is a0ec0d286f1f8911617ba0a7fddcd9a0e0108d6d, authored by Brooklyn Nicholson, addressing NousResearch/hermes-agent issue 119176. The frozen release source is 818c13be1dc4fd28987e1e881a9408224afd4535; downstream starts at 606f7e557c13a0789a2420f7adf6181becf60d75. The central CommandDef registry and existing CLI/Gateway dispatchers own canonicalization. The TUI local registry and curated Desktop allowlist mirror the alias without introducing an independent handler.

Local Desktop/TUI execution is owned by tui_gateway/methods_tools.py, methods_session.py and server.py. The composer owner is apps/desktop/src/app/chat/composer/hooks/use-composer-submit.ts. Dynamic RPC registration and agent methods are reviewed directly in addition to CodeGraph traces; an empty static affected-test set is not evidence of no impact.

## Contract

/s, /S and /steer preserve argument case and deliver through the existing live agent after the current tool boundary. Empty arguments retain usage errors. CLI/Gateway authorization and session isolation remain inherited from the canonical owner. An idle cached agent is not an active run: explicit idle steering uses the existing next-turn payload/FIFO behavior. Image-bearing composer submissions retain existing attachment routing.

Control slash dispatch must preserve parked clarify and MCP setup cards until an explicit response or Stop. Plain followups retain their existing skip behavior. The real provider request retains its prefix and role sequence; the steer nonce is appended once to the real tool result rather than becoming a duplicate user message.

Local steer admission and caller-specific correction metadata are serialized with the idle transition by the existing history lock. Settle consumes the finalizer result and late agent buffer before exposing idle. Accepted notes retain order and are delivered once through the existing FIFO. A private, server-owned queue-envelope flag preserves explicit steering equal to the original prompt across retained-error snapshots; ordinary stale self-copy filtering remains active. Envelopes of different provenance do not merge.

Stop rejects new steering while the local turn settles. It cancels accepted notes still in the local buffer, finalizer result, settled FIFO, or claimed explicit-steer envelope. Local buffer discard occurs before hard interrupt/pending-card cleanup can release a parked tool. Optional missing/throwing legacy drains do not prevent hard interrupt and cleanup. Idle explicit input after Stop starts a fresh turn while preserving the queue generation. Ordinary generation restoration, transport and image ownership retain their existing contracts.

Already delivered historical tool markers are preserved. Helper-local notes taken before Stop, compute-host-owned Stop, classic CLI Stop and messaging Stop have separate owner boundaries; the additional B07 lead tracks unqualified cancellation/restore races. F03 evidence does not claim these broader Stop owners are repaired.

## Oracle and validation

Python tests use actual public CLI/Gateway/RPC dispatch, AIAgent steer buffering/tool-result application, real Stop and the real FIFO consumer. Only a model invocation is replaced by an effect ledger. Deterministic barriers cover admission/settle, old post-turn vs a later agent, retained errors, cancellation publication, generation recheck and cancelled-tool result recording.

The native oracle runs Windows Electron and the actual Python backend in a disposable HOME. An external loopback model fixture scripts real clarify calls and observes deep-copied provider requests; auxiliary requests do not advance the conversation cursor. It observes canonical/lower/upper alias effects, empty and whitespace rejection, idle transcript preservation and Stop followed by fresh input. Process identities include PID, creation time, executable and arguments; cleanup requires process exit, no surviving owned descendants and a refused loopback TCP connection.

Mutation qualification requires GREEN before and after each disposable source mutation, an actual behavioral assertion failure and exact source restoration. Alias removal, success without effects, blanket denial, wrong execution owner, cached-idle admission, late handoff loss, unlocked admission, stolen later-turn buffer, lost provenance/metadata and cancellation regressions are separate mutations. Composer clarify/MCP auto-skip mutations have independent effect evidence.

Final commands, source/artifact hashes, counts, limitations, independent review and local commit identity belong in the family receipt. Full campaign completion remains independent of F03 qualification.
