# Carry-surface metrics, 2026-08-26

Frozen upstream: b51c055a12220f8c7c18660e8599365012e19532

| Metric | Value |
| --- | ---: |
| All fork-specific LOC | 3234270 |
| Upstream-owned fork LOC | 1574818 |
| Fork-owned LOC | 1659452 |
| UTR | 0.486916 |
| Carry Surface | 5166 files |
| CWC | 87517298 |

LOC is added plus deleted lines relative to the frozen upstream tree.
The `_docs/` tree (including these reports) is excluded to avoid
self-referential totals from impl logs and regenerated metrics.
Totals are computed from committed HEAD, not a dirty worktree.
Coupling is 3 for CARRY.yaml paths, 2 for other runtime/source paths,
and 1 for tests, docs, workflows, and generated documentation.

## Highest CWC paths

| Path | Frequency | Patch | Coupling | CWC |
| --- | ---: | ---: | ---: | ---: |
| gateway/run.py | 158 | 33405 | 2 | 10555980 |
| hermes_cli/web_server.py | 95 | 21660 | 3 | 6173100 |
| cli.py | 77 | 25158 | 2 | 3874332 |
| tui_gateway/server.py | 96 | 19744 | 2 | 3790848 |
| hermes_state.py | 112 | 16246 | 2 | 3639104 |
| hermes_cli/main.py | 73 | 15992 | 3 | 3502248 |
| agent/auxiliary_client.py | 89 | 12968 | 3 | 3462456 |
| hermes_cli/update_cmd.py | 85 | 12281 | 3 | 3131655 |
| agent/conversation_loop.py | 85 | 9564 | 3 | 2438820 |
| agent/context_compressor.py | 82 | 10081 | 2 | 1653284 |
| run_agent.py | 74 | 10338 | 2 | 1530024 |
| agent/conversation_compression.py | 95 | 7122 | 2 | 1353180 |
| hermes_cli/config_defaults.py | 64 | 6668 | 3 | 1280256 |
| agent/chat_completion_helpers.py | 73 | 8270 | 2 | 1207420 |
| cron/scheduler.py | 56 | 9852 | 2 | 1103424 |
| hermes_cli/models.py | 67 | 7826 | 2 | 1048684 |
| gateway/slash_commands.py | 71 | 7237 | 2 | 1027654 |
| hermes_cli/auth.py | 46 | 10823 | 2 | 995716 |
| hermes_cli/gateway.py | 57 | 8378 | 2 | 955092 |
| gateway/platforms/base.py | 36 | 8402 | 3 | 907416 |
| tools/mcp_tool.py | 46 | 9777 | 2 | 899484 |
| hermes_cli/kanban_db.py | 30 | 13908 | 2 | 834480 |
| hermes_cli/config.py | 54 | 7148 | 2 | 771984 |
| plugins/platforms/telegram/adapter.py | 30 | 11675 | 2 | 700500 |
| agent/agent_runtime_helpers.py | 55 | 6296 | 2 | 692560 |

This is a coupling report, not a target to improve by relocating code
without reducing its actual dependency on upstream behavior.
