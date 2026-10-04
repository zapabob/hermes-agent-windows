# Standalone & Local Verification Scripts

This directory contains standalone execution harnesses, verification scripts, and local utilities that are not part of the core agent root entrypoints.

## Overview

In accordance with official Hermes repository standards and root layout hygiene:
- **Core root modules** (`run_agent.py`, `cli.py`, `model_tools.py`, `batch_runner.py`, `hermes_state.py`, etc.) remain in the root directory for upstream compatibility.
- **Standalone execution utilities, test harnesses, and local maintenance scripts** are organized here under `scripts/standalone/` so the repository root remains clean, reproducible, and compliant with official upstream releases.

## Inventory of Scripts

| Script | Purpose | Typical Invocation |
|---|---|---|
| p`mini_swe_runner.py` | SWE runner supporting Hermes trajectory format across execution environments (local, Docker, Modal) | uv run python scripts/standalone/mini_swe_runner.py --help |
| `sync_memory.py` **(CANONICAL)** | Unified social memory synchronizer (Gateway sessions -> Ebbinghaus SQLite -> Obsidian wiki) | `uv run python scripts/standalone/sync_memory.py` | |
| p`cron_sync_script.py` | Automated Cron background synchronization for Ebbinghaus & social trace scrubbing | uv run python scripts/standalone/cron_sync_script.py |
� p`dream_verify_insert.py` | Quick SQLite probe for validating Ebbinghaus consolidated memory records | uv run python scripts/standalone/dream_verify_insert.py |
| p`reply_mentions_test.py` | Direct verification and dry-run test harness for `lm-twitterer` reply mentions | uv run python scripts/standalone/reply_mentions_test.py |

## Execution Guidelines

1. **Environment**: Always run within the project virtual environment via `uv run python ...` or `py -3 ...`.
2. **Secrets & Configuration**:
   - Credentials must come from standard configuration files (`~/.hermes/config.yaml` or `~/.hermes/.env`), never hardcoded in scripts.
3. **Repository Harness**:
   - Scripts in this directory resolve the repository root dynamically (`Path(__file__).resolve().parents[2]`) to ensure seamless imports of `agent.*`, `tools.*`, and `scripts.*`.



## Related Guides

- Root Policy: [`../../AGENTS.md`](../../AGENTS.md)
- Local Workspace Guide: [`../../fork/local-workspace/README.md`](../../fork/local-workspace/README.md)
- Directory Agent Rules: [`AGENTS.md`](AGENTS.md)
