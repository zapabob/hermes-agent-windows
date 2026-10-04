# Standalone Scripts — Agent Rules

This directory contains standalone execution harnesses, verification scripts, and diagnostic tools.

## Rules for AI Agents
1. **Upstream Alignment & Root Hygiene**:
   - Do not move core root entrypoints (`run_agent.py`, `cli.py`, `model_tools.py`, `hermes_state.py`, `batch_runner.py`) into this folder. Core entrypoints must stay at root.
   - Place any new standalone batch runners, non-core diagnostics, or localized cron scripts in `scripts/standalone/` or `tmp/probes/` rather than cluttering the repository root.

2. **Canonical ownership**: `scripts/standalone/sync_memory.py` is the single source of truth for the social-memory sync orchestrator. The repo-root `sync_memory.py` re-exports it and holds no logic. Never edit both; edit this one.

3. **Harness & Path Safety**:
   - Any script in this folder that needs core modules must resolve `REPO_ROOT` dynamically (`Path(__file__).resolve().parents[2]`) and insert it into `sys.path`.
   - Never rely on relative paths that assume the current working directory is the repository root without explicit path resolution.

4. **Execution & Credentials**:
   - Run with project virtualenv (`uv run python ...`).
   - Never write or hardcode API keys, auth tokens, or private endpoints into scripts in this directory.

5. **Logging & Quality Standards**:
   - Prefer `logging` over `print` statements in production scripts.
   - Maintain UTF-8 encoding.

## Related

- Repository Root Policy: [`../../AGENTS.md`](../../AGENTS.md)
- Fork Policy: [`../../fork/AGENTS.md`](../../fork/AGENTS.md)
- README: [`README.md`](README.md)
