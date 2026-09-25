# README trilingual rewrite (King's English / 日本語 / 简体中文)

- Date: 2026-09-26 (JST)
- Agent: Cursor
- Branch: `docs/readme-trilingual-20260926` (from `origin/main` @ `3beeca89e8e`, after PR #148)

## Overview

Rewrote `README.md`, `README.ja.md` and `README.zh-CN.md` so that all three
describe the current feature set with the same section structure. The English
file remains canonical; the Japanese and Chinese files follow it section by
section.

## Background and requirements

- The user asked for the three language READMEs to reflect current features,
  keeping the language switcher.
- Claims had to be verified against code and ledgers rather than memory.
- The fork is BYOK/OAuth-first with no required hosted service; this had to be
  stated accurately.
- The hakua-memory backend and LLM judge for Ebbinghaus were to be mentioned
  only if merged on `origin/main`.

## Assumptions and decisions

- **Switcher preserved**: the `<p align="center">` language bar (already in the
  Japanese and Chinese files) was added to `README.md` as well; the inline
  `<details open>` 日本語 / `<details>` 简体中文 blocks required by
  `tests/downstream/test_readme_contract.py` are kept in `README.md`.
- **Contract test is authoritative**: section headings 1–16, the quick-start
  headings, `154 plug-in manifests`, `Model providers (42)` and the localised
  equivalents are preserved. The 154 figure is now framed as the integration
  inventory snapshot, with the current tree count (156) stated alongside.
- **Memory work omitted**: `plugins/memory/ebbinghaus` on `origin/main` contains
  no hakua backend or `judge.py`, and no merged PR covers it, so it is not
  mentioned.
- **Tailscale**: only Tailscale Serve scripts exist (`Manage-HermesTailscaleServe.ps1`);
  no Funnel script exists, so Funnel is not claimed.
- **Non-target READMEs**: `README.es.md` and `README.ur-pk.md` were left unchanged.

## Evidence used for the inventory

| Claim | Evidence |
| --- | --- |
| Version 0.21.3, snapshot `b51c055…`, channels | `downstream/distribution.json`, `pyproject.toml` |
| Verified feature rows and retired watchdog backend | `FEATURES.yaml` (`watchdog-managed-desktop-backend: retired`, `windows-desktop-single-owner-backend: verified`) |
| Watchdog owner-path removal | PRs #133, #134, #136 |
| Implementation router, `/engineer`, `engineering_run` | PR #143, `plugins/implementation_router/README.md`, `tests/implementation_router/` |
| Relay 0.8 trace-header stripping, credential masking in base URLs | PR #148, commit `5fcbfad3bfe`, `agent/redact.py::redact_base_url` |
| OAuth providers | `hermes_cli/auth.py` `PROVIDER_REGISTRY` (Nous device code; Codex, xAI, Qwen external OAuth; MiniMax OAuth), Claude Code credential reuse in `hermes_cli/main.py` |
| CLI subcommands (`proxy`, `fallback`, `moa`, `harness`, `security`, `egress`, `secrets`, `memory`, `journey`, `mcp`) | `hermes --help` run from the worktree |
| Plug-in counts | 156 `plugin.yaml` under `plugins/`; 42 model providers; 22 platform plug-ins; 9 memory providers; 53 standard root plug-ins + `lmcache` |
| Built-in gateway adapters | `gateway/platforms/*.py` |
| New submodule `plugins/artemis` | `.gitmodules`, `gh repo view zapabob/artemis` |

## Changed files

- `README.md`
- `README.ja.md`
- `README.zh-CN.md`
- `_docs/2026-09-26_readme-trilingual-rewrite_Cursor.md` (this file)

## Implementation details

- Added a "What this fork adds" section and moved "Plug-ins and Git submodules"
  before section 1 in all three files so that the structure is identical.
- Feature matrix rebuilt from `FEATURES.yaml`: Desktop backend single owner,
  watchdog authority, provider fallback, Ebbinghaus test, implementation router.
- Root plug-in table: added `hermes-antigravity` and `implementation_router` (53).
- Submodule table: added `plugins/artemis`; marked `vendor/shinka-osint` as a
  private repository.
- Security section: base-URL masking, Relay trace-header policy, `hermes security`,
  `hermes egress`, `hermes secrets`.
- King's English spelling in the English file (behaviour, licence, artefacts,
  initialisation, organise-family words).

## Claims removed as outdated

- Japanese/Chinese: Go watchdog as "the only outer auto-restart authority" that
  monitors packaged Desktop and publishes a prewarmed backend manifest (retired).
- Japanese/Chinese: matrix row "Recovery: watchdog-managed Desktop backend".
- Japanese/Chinese: bullet "external Go watchdog that recovers Desktop/backend".
- All: "51 bundled root plug-ins" (now 53); submodule table missing `plugins/artemis`.
- English: statement that the Japanese/Chinese READMEs are older detailed
  versions; duplicated non-endorsement sentence; dated 2026-09-08 campaign test
  tallies and campaign comparison SHAs (kept in `_docs/` and `CARRY.yaml`).

## Commands run

```powershell
git fetch origin
git worktree add -b docs/readme-trilingual-20260926 ..\hermes-readme-20260926 origin/main
..\hermes-agent\.venv\Scripts\python.exe -m hermes_cli.main --help
..\hermes-agent\.venv\Scripts\python.exe -m pytest tests/downstream/test_readme_contract.py tests/downstream/test_repository_identity.py -q -p no:cacheprovider
..\hermes-agent\.venv\Scripts\python.exe tmp/probes/readme_linkcheck.py
curl.exe -s -o NUL -w "%{http_code}" -L <each external GitHub URL>
```

## Tests and verification

- `tests/downstream/test_readme_contract.py` + `test_repository_identity.py`: 9 passed.
- Link check (`tmp/probes/readme_linkcheck.py`, gitignored): 0 dead relative
  links, 0 missing code paths, no BOM, identical numbered sections 1–16 in all
  three files.
- External URLs: all HTTP 200 except `zapabob/ShinkaEvolve-OSINT`, which is a
  private repository (confirmed with `gh repo view`) and is now labelled as such.

## Residual risks

- Plug-in counts are a snapshot of the tree and will drift as plug-ins are added.
- Translation nuance was reviewed by the author only; no native-speaker review.
- `README.es.md` and `README.ur-pk.md` remain on older content.

## Recommended next actions

- Once the hakua-memory / LLM judge PR merges, add a sentence to section 9 in
  all three files.
- Consider replacing the fixed-count assertions in the README contract test with
  an invariant (for example, "the README count matches the inventory").
