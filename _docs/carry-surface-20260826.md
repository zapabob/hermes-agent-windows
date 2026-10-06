# Carry-surface metrics, 2026-08-26

Frozen upstream: b51c055a12220f8c7c18660e8599365012e19532

| Metric | Value |
| --- | ---: |
| All fork-specific LOC | 3131973 |
| Upstream-owned fork LOC | 1562536 |
| Fork-owned LOC | 1569437 |
| UTR | 0.498898 |
| Carry Surface | 5128 files |
| CWC | 86823638 |

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
| hermes_cli/web_server.py | 95 | 21516 | 3 | 6132060 |
| cli.py | 77 | 25129 | 2 | 3869866 |
| tui_gateway/server.py | 96 | 19419 | 2 | 3728448 |
| hermes_state.py | 112 | 16246 | 2 | 3639104 |
| hermes_cli/main.py | 73 | 15992 | 3 | 3502248 |
| agent/auxiliary_client.py | 89 | 12919 | 3 | 3449373 |
| hermes_cli/update_cmd.py | 85 | 12281 | 3 | 3131655 |
| agent/conversation_loop.py | 85 | 9588 | 3 | 2444940 |
| agent/context_compressor.py | 82 | 9924 | 2 | 1627536 |
| run_agent.py | 74 | 10271 | 2 | 1520108 |
| agent/conversation_compression.py | 95 | 6964 | 2 | 1323160 |
| hermes_cli/config_defaults.py | 64 | 6625 | 3 | 1272000 |
| agent/chat_completion_helpers.py | 73 | 8052 | 2 | 1175592 |
| cron/scheduler.py | 56 | 9815 | 2 | 1099280 |
| hermes_cli/models.py | 67 | 7825 | 2 | 1048550 |
| gateway/slash_commands.py | 71 | 7095 | 2 | 1007490 |
| hermes_cli/auth.py | 46 | 10823 | 2 | 995716 |
| hermes_cli/gateway.py | 57 | 8378 | 2 | 955092 |
| gateway/platforms/base.py | 36 | 8381 | 3 | 905148 |
| tools/mcp_tool.py | 46 | 9376 | 2 | 862592 |
| hermes_cli/kanban_db.py | 30 | 13908 | 2 | 834480 |
| hermes_cli/config.py | 54 | 6960 | 2 | 751680 |
| plugins/platforms/telegram/adapter.py | 30 | 11675 | 2 | 700500 |
| agent/agent_runtime_helpers.py | 55 | 6292 | 2 | 692120 |

This is a coupling report, not a target to improve by relocating code
without reducing its actual dependency on upstream behavior.
