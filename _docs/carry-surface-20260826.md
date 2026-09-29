# Carry-surface metrics, 2026-08-26

Frozen upstream: b51c055a12220f8c7c18660e8599365012e19532

| Metric | Value |
| --- | ---: |
| All fork-specific LOC | 2761304 |
| Upstream-owned fork LOC | 1551162 |
| Fork-owned LOC | 1210142 |
| UTR | 0.561750 |
| Carry Surface | 5099 files |
| CWC | 86462712 |

LOC is added plus deleted lines relative to the frozen upstream tree.
The `_docs/` tree (including these reports) is excluded to avoid
self-referential totals from impl logs and regenerated metrics.
Totals are computed from committed HEAD, not a dirty worktree.
Coupling is 3 for CARRY.yaml paths, 2 for other runtime/source paths,
and 1 for tests, docs, workflows, and generated documentation.

## Highest CWC paths

| Path | Frequency | Patch | Coupling | CWC |
| --- | ---: | ---: | ---: | ---: |
| gateway/run.py | 158 | 32765 | 2 | 10353740 |
| hermes_cli/web_server.py | 95 | 21520 | 3 | 6133200 |
| cli.py | 77 | 25060 | 2 | 3859240 |
| tui_gateway/server.py | 96 | 19430 | 2 | 3730560 |
| hermes_state.py | 112 | 16238 | 2 | 3637312 |
| hermes_cli/main.py | 73 | 15990 | 3 | 3501810 |
| agent/auxiliary_client.py | 89 | 12872 | 3 | 3436824 |
| hermes_cli/update_cmd.py | 85 | 11474 | 3 | 2925870 |
| agent/conversation_loop.py | 85 | 9641 | 3 | 2458455 |
| agent/context_compressor.py | 82 | 9921 | 2 | 1627044 |
| run_agent.py | 74 | 10265 | 2 | 1519220 |
| agent/conversation_compression.py | 95 | 6964 | 2 | 1323160 |
| hermes_cli/config_defaults.py | 64 | 6618 | 3 | 1270656 |
| agent/chat_completion_helpers.py | 73 | 8051 | 2 | 1175446 |
| cron/scheduler.py | 56 | 9812 | 2 | 1098944 |
| hermes_cli/models.py | 67 | 7722 | 2 | 1034748 |
| gateway/slash_commands.py | 71 | 7095 | 2 | 1007490 |
| hermes_cli/auth.py | 46 | 10822 | 2 | 995624 |
| hermes_cli/gateway.py | 57 | 8320 | 2 | 948480 |
| gateway/platforms/base.py | 36 | 8381 | 3 | 905148 |
| tools/mcp_tool.py | 46 | 9350 | 2 | 860200 |
| hermes_cli/kanban_db.py | 30 | 13923 | 2 | 835380 |
| hermes_cli/config.py | 54 | 6828 | 2 | 737424 |
| plugins/platforms/telegram/adapter.py | 30 | 11674 | 2 | 700440 |
| agent/agent_runtime_helpers.py | 55 | 6288 | 2 | 691680 |

This is a coupling report, not a target to improve by relocating code
without reducing its actual dependency on upstream behavior.
