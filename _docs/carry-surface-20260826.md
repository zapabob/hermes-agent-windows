# Carry-surface metrics, 2026-08-26

Frozen upstream: b51c055a12220f8c7c18660e8599365012e19532

| Metric | Value |
| --- | ---: |
| All fork-specific LOC | 2679323 |
| Upstream-owned fork LOC | 1532811 |
| Fork-owned LOC | 1146512 |
| UTR | 0.572089 |
| Carry Surface | 5021 files |
| CWC | 80093421 |

LOC is added plus deleted lines relative to the frozen upstream tree.
Generated metric reports are excluded to avoid self-referential totals.
Coupling is 3 for CARRY.yaml paths, 2 for other runtime/source paths,
and 1 for tests, docs, workflows, and generated documentation.

## Highest CWC paths

| Path | Frequency | Patch | Coupling | CWC |
| --- | ---: | ---: | ---: | ---: |
| gateway/run.py | 158 | 32603 | 2 | 10302548 |
| hermes_cli/web_server.py | 95 | 21737 | 2 | 4130030 |
| cli.py | 77 | 25125 | 2 | 3869250 |
| tui_gateway/server.py | 96 | 19388 | 2 | 3722496 |
| hermes_state.py | 112 | 16244 | 2 | 3638656 |
| hermes_cli/update_cmd.py | 85 | 11058 | 3 | 2819790 |
| hermes_cli/main.py | 73 | 15984 | 2 | 2333664 |
| agent/auxiliary_client.py | 89 | 12702 | 2 | 2260956 |
| agent/context_compressor.py | 82 | 9929 | 2 | 1628356 |
| agent/conversation_loop.py | 85 | 9520 | 2 | 1618400 |
| run_agent.py | 74 | 10183 | 2 | 1507084 |
| agent/conversation_compression.py | 95 | 6964 | 2 | 1323160 |
| cron/scheduler.py | 56 | 9827 | 2 | 1100624 |
| agent/chat_completion_helpers.py | 73 | 7503 | 2 | 1095438 |
| hermes_cli/models.py | 67 | 7702 | 2 | 1032068 |
| gateway/slash_commands.py | 71 | 7090 | 2 | 1006780 |
| hermes_cli/auth.py | 46 | 10798 | 2 | 993416 |
| hermes_cli/gateway.py | 57 | 8320 | 2 | 948480 |
| gateway/platforms/base.py | 36 | 8357 | 3 | 902556 |
| hermes_cli/config_defaults.py | 64 | 6604 | 2 | 845312 |
| hermes_cli/kanban_db.py | 30 | 13923 | 2 | 835380 |
| tools/mcp_tool.py | 46 | 9049 | 2 | 832508 |
| hermes_cli/config.py | 54 | 6789 | 2 | 733212 |
| plugins/platforms/telegram/adapter.py | 30 | 11674 | 2 | 700440 |
| agent/agent_runtime_helpers.py | 55 | 6279 | 2 | 690690 |

This is a coupling report, not a target to improve by relocating code
without reducing its actual dependency on upstream behavior.
