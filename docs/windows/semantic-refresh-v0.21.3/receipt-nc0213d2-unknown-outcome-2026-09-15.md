# Receipt — NC-0213-D2 unknown-outcome / tool failure inference

| Field | Value |
|---|---|
| Slice | NC-0213-D2 |
| Campaign | windows-native-carry-v0.21.3 |
| U_NEXT | `345cd2b057a452236de401d3534b8502a7465e8d` |
| U commits | `6d62c87997`, `5e0bde99d1`, `d3699f2fc1`, `3b733a7c8a` |
| Decision | ADOPT |
| Method | COMPOSE into desktop tool presentation owners |
| Contract | failureDeclared gate; completedAt without result → warning; notice tier; toolResultRecord separates metadata; no auto-red from stdout diagnostics |
| Command | vitest (workspace install required; deferred to promotion gate) + static COMPOSE from U tests ported |
| Exact tested SHA | *(filled after commit)* |
| main integration | NOT_DONE |

## Files
- apps/desktop/src/lib/tool-result-metadata.ts (new)
- apps/desktop/src/lib/tool-result-summary.ts (+test)
- apps/desktop/src/components/assistant-ui/tool/fallback-model/*
- apps/desktop/src/components/assistant-ui/thread/changed-files.ts
- i18n resultUnavailable keys
