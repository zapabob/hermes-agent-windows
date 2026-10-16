# Carry-surface metrics, 2026-08-26

Frozen upstream: b51c055a12220f8c7c18660e8599365012e19532

| Metric | Value |
| --- | ---: |
| All fork-specific LOC | 3185519 |
| Upstream-owned fork LOC | 1568906 |
| Fork-owned LOC | 1616613 |
| UTR | 0.492512 |
| Carry Surface | 5147 files |
| CWC | 87089662 |

LOC is added plus deleted lines relative to the frozen upstream tree.
The `_docs/` tree (including these reports) is excluded to avoid
self-referential totals from impl logs and regenerated metrics.
Totals are computed from committed HEAD, not a dirty worktree.
Coupling is 3 for CARRY.yaml paths, 2 for other runtime/source paths,
and 1 for tests, docs, workflows, and generated documentation.

## Highest CWC paths

| Path | Frequency | Patch | Coupling | CWC |
| --- | ---: | ---: | ---: | ---: |
| gateway/run.py | 158 | 32784 | 2 | 10359744 |
| hermes_cli/web_server.py | 95 | 21567 | 3 | 6146595 |
| cli.py | 77 | 25131 | 2 | 3870174 |
| tui_gateway/server.py | 96 | 19713 | 2 | 3784896 |
| hermes_state.py | 112 | 16246 | 2 | 3639104 |
| hermes_cli/main.py | 73 | 15992 | 3 | 3502248 |
| agent/auxiliary_client.py | 89 | 12968 | 3 | 3462456 |
| hermes_cli/update_cmd.py | 85 | 12281 | 3 | 3131655 |
| agent/conversation_loop.py | 85 | 9588 | 3 | 2444940 |
| agent/context_compressor.py | 82 | 9924 | 2 | 1627536 |
| run_agent.py | 74 | 10275 | 2 | 1520700 |
| agent/conversation_compression.py | 95 | 7036 | 2 | 1336840 |
| hermes_cli/config_defaults.py | 64 | 6625 | 3 | 1272000 |
| agent/chat_completion_helpers.py | 73 | 8210 | 2 | 1198660 |
| cron/scheduler.py | 56 | 9852 | 2 | 1103424 |
| hermes_cli/models.py | 67 | 7825 | 2 | 1048550 |
| gateway/slash_commands.py | 71 | 7187 | 2 | 1020554 |
| hermes_cli/auth.py | 46 | 10823 | 2 | 995716 |
| hermes_cli/gateway.py | 57 | 8378 | 2 | 955092 |
| gateway/platforms/base.py | 36 | 8388 | 3 | 905904 |
| tools/mcp_tool.py | 46 | 9708 | 2 | 893136 |
| hermes_cli/kanban_db.py | 30 | 13908 | 2 | 834480 |
| hermes_cli/config.py | 54 | 7134 | 2 | 770472 |
| plugins/platforms/telegram/adapter.py | 30 | 11675 | 2 | 700500 |
| agent/agent_runtime_helpers.py | 55 | 6295 | 2 | 692450 |

This is a coupling report, not a target to improve by relocating code
without reducing its actual dependency on upstream behavior.
