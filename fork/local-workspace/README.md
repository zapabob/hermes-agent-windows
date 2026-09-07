# Local Workspace (AI Workstation Harness)

Files listed here often appear **directly under the repository root** on the
operator workstation. Most are **gitignored** — kept on disk for local workflows,
not part of the canonical product surface.

**Do not delete** these files to "clean up" unless the operator asks. **Do not
commit** ignored scratch. **Do use CodeGraph** before deciding a root file is
scratch vs packaging (`npx @colbymchenry/codegraph query|impact`).

This document exists so agents understand the **Windows AI workstation harness**
layout used on this machine.

## Preferred destinations (2026-09-08)

| Type | Path | Git |
|------|------|-----|
| Media / social renders | `output/media/` | ignored |
| Reports / disaster JSON / career exports | `output/reports/` | ignored |
| Run logs | `output/logs/` | ignored |
| Ad-hoc probes (`_tmp_*`, `analyze_*.py`, `test_*.py`) | `tmp/probes/` | ignored |
| Nested local projects, path dumps, PR JSON | `tmp/snapshots/` | ignored |
| Tracked research / probe archives | `notes/archives/` | tracked |
| Architecture map | `docs/maps/REPOSITORY_MAP.md` | tracked |
| Windows handoff SOP | `docs/windows/HANDOFF_*.md` | tracked |
| Implementation logs | `_docs/` | ignored |

## Categories

### Media and social scratch

| Pattern | Examples | Purpose |
|---------|----------|---------|
| `output/media/*` | `ohayo_tweet.mp4`, `latest_vrchat.png` | VRChat / Hakua content drafts |
| `tmp/snapshots/hermes_v*.py`, `output/media/hermes_v*_with_audio.mp4` | versioned demo renders | Local video generation experiments |

### Disaster / monitoring JSON (ephemeral)

| Files | Purpose |
|-------|---------|
| `output/reports/eq.json`, `quake.json`, `tsunami.json` | Earthquake API snapshots |
| `tmp/probes/check_quake_tsunami.py`, `process_disaster.py` | One-off processing scripts |

### Logs and state text

| Files | Purpose |
|-------|---------|
| `output/logs/*.log`, `output/reports/report.txt` | Local run output |
| `output/reports/current_time.txt`, `.last_*_index` | Scratch indices |

### Diagnostics (gitignored)

| Pattern | Purpose |
|---------|----------|
| `tmp/probes/_diag_*.py`, `temp_*.py`, `_tmp_*.py` | Ad-hoc probes |
| `tmp/probes/test_*.py` | Throwaway tool tests — prefer `tests/` |

### Nested / broken path dumps

| Pattern | Purpose |
|---------|----------|
| `tmp/snapshots/windows-caches/%SystemDrive%` | Accidental Windows path dumps |
| `tmp/snapshots/broken-paths/` | Malformed directory names from bad joins |
| `tmp/snapshots/nested-projects/` | Local nested checkouts (e.g. HyperFrames demos) |

### Secrets (never commit)

| Pattern | Purpose |
|---------|----------|
| `client_secret_*.json` | OAuth client secrets |
| `.env`, `cli-config.yaml` | Credentials and local paths |

## Official vs scratch

| Official (tracked, stay at root) | Scratch / archives |
|----------------------------------|--------------------|
| `run_agent.py`, `cli.py`, `model_tools.py` | `tmp/probes/*` |
| `FEATURES.yaml`, `CARRY.yaml`, `UPSTREAM_ADOPTION.yaml` | `output/reports/*` |
| `scripts/daily_*.py` | `tmp/snapshots/*` |
| `plugins/`, `skills/` | `notes/archives/*` (tracked when needed) |

### Tracked notes

Operator drafts and relocated archives that must stay in git but must not
clutter the root live under [`../../notes/`](../../notes/):

| Path | Purpose |
|------|---------|
| `notes/archives/mcp-research-data/` | UE bench / discovery JSON (relocated from root) |
| `notes/archives/net-home-probe-results/` | Network probe baselines |
| `notes/archives/artifacts/` | Measurement artifacts |

See [`AGENTS.md`](AGENTS.md) for agent handling rules. Root policy summary:
[`../../AGENTS.md`](../../AGENTS.md) §§16–17.
