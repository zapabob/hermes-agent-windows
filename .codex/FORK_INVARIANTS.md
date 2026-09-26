# Fork invariants

1. The frozen upstream input is immutable and commits newer than the recorded
   snapshot are out of scope.
2. Official stable and public APIs are the preferred integration boundary.
3. Verified downstream features are preserved until replacement parity is
   demonstrated by code and tests.
4. Windows 11 native remains Tier 1 independently of upstream priorities.
5. Runtime restart authority is scoped by role. On the supported Windows
   Desktop topology, Electron owns the Desktop Python backend lifecycle; the
   external Go watchdog at `scripts/windows/watchdog-go` may destructively
   manage only an embedding `llama-server` instance it launched and owns.
   Observation alone grants neither component authority over the other role.
6. Hermes core retains the sole session, approval, profile, gateway ownership,
   model-catalogue, and tool-registry authorities.
7. Prompt-cache prefixes, message-role alternation, profile isolation, and
   credential boundaries must not regress.
8. Plugin discovery entrypoints remain where official discovery expects them;
   shared fork implementation may move behind downstream-owned modules.
9. State paths use official profile-aware Hermes path functions. User-visible
   paths use the official display helper.
10. Destructive and update operations are deterministic, auditable, and
    recoverable. Local, CI, runtime, and restart-durability evidence are
    reported separately.
