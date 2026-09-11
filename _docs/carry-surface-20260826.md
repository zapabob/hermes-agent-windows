# Carry-surface metrics, 2026-08-26

Frozen upstream: b51c055a12220f8c7c18660e8599365012e19532

| Metric | Value |
| --- | ---: |
| All fork-specific LOC | 2709591 |
| Upstream-owned fork LOC | 1545605 |
| Fork-owned LOC | 1163986 |
| UTR | 0.570420 |
| Carry Surface | 5075 files |
| CWC | 86068502 |

LOC is added plus deleted lines relative to the frozen upstream tree.
Generated metric reports are excluded to avoid self-referential totals.
Coupling is 3 for CARRY.yaml paths, 2 for other runtime/source paths,
and 1 for tests, docs, workflows, and generated documentation.

## Highest CWC paths

| Path | Frequency | Patch | Coupling | CWC |
| --- | ---: | ---: | ---: | ---: |
| gateway/run.py | 158 | 32575 | 2 | 10293700 |
| hermes_cli/web_server.py | 95 | 21370 | 3 | 6090450 |
| cli.py | 77 | 24994 | 2 | 3849076 |
| tui_gateway/server.py | 96 | 19383 | 2 | 3721536 |
| hermes_state.py | 112 | 16244 | 2 | 3638656 |
| hermes_cli/main.py | 73 | 15990 | 3 | 3501810 |
| agent/auxiliary_client.py | 89 | 12770 | 3 | 3409590 |
| hermes_cli/update_cmd.py | 85 | 11438 | 3 | 2916690 |
| agent/conversation_loop.py | 85 | 9526 | 3 | 2429130 |
| agent/context_compressor.py | 82 | 9921 | 2 | 1627044 |
| run_agent.py | 74 | 10183 | 2 | 1507084 |
| agent/conversation_compression.py | 95 | 6964 | 2 | 1323160 |
| hermes_cli/config_defaults.py | 64 | 6611 | 3 | 1269312 |
| agent/chat_completion_helpers.py | 73 | 7601 | 2 | 1109746 |
| cron/scheduler.py | 56 | 9812 | 2 | 1098944 |
| hermes_cli/models.py | 67 | 7713 | 2 | 1033542 |
| gateway/slash_commands.py | 71 | 7090 | 2 | 1006780 |
| hermes_cli/auth.py | 46 | 10809 | 2 | 994428 |
| hermes_cli/gateway.py | 57 | 8320 | 2 | 948480 |
| gateway/platforms/base.py | 36 | 8368 | 3 | 903744 |
| hermes_cli/kanban_db.py | 30 | 13923 | 2 | 835380 |
| tools/mcp_tool.py | 46 | 9074 | 2 | 834808 |
| hermes_cli/config.py | 54 | 6789 | 2 | 733212 |
| plugins/platforms/telegram/adapter.py | 30 | 11674 | 2 | 700440 |
| agent/agent_runtime_helpers.py | 55 | 6284 | 2 | 691240 |

This is a coupling report, not a target to improve by relocating code
without reducing its actual dependency on upstream behavior.
