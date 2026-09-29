"""``hermes ebbinghaus`` CLI: opt-in LLM-as-judge review of stored memories.

Registered through the memory-plugin CLI discovery (active provider only).
Results are machine-readable JSON on stdout and contain ids and counts only,
never memory text.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _judge(args) -> int:
    from agent.plugin_llm import PluginLlm

    from . import EbbinghausMemoryProvider, _load_plugin_config
    from .judge import PLUGIN_ID, FindingsStore, JudgeSettings, MemoryJudge

    config = _load_plugin_config()
    settings = JudgeSettings.from_plugin_config(config)
    dry_run = not args.run
    if not dry_run and not settings.enabled:
        _emit({
            "error": "judge disabled",
            "hint": "set plugins.ebbinghaus.judge_enabled: true in config.yaml, or use --estimate",
        })
        return 2

    provider = EbbinghausMemoryProvider(config)
    provider.initialize("ebbinghaus-judge")
    findings = FindingsStore.open_default()
    try:
        judge = MemoryJudge(
            provider._store,  # noqa: SLF001 - same plugin package
            findings,
            settings,
            llm=None if dry_run else PluginLlm(plugin_id=PLUGIN_ID),
            store_backend=provider.store_backend,
        )
        report = judge.run(dry_run=dry_run, max_calls=args.max_calls, memory_ids=args.memory_id or None)
        payload = report.as_dict()
        payload["store_backend"] = provider.store_backend
        payload["judge_enabled"] = settings.enabled
        payload["active_memories"] = provider._store.stats().get("active_count")  # noqa: SLF001
        _emit(payload)
        return 0
    finally:
        findings.close()
        provider.shutdown()


def _findings(args) -> int:
    from .judge import FindingsStore

    store = FindingsStore.open_default()
    try:
        _emit({"findings": store.list_findings(limit=args.limit, review_state=args.state)})
        return 0
    finally:
        store.close()


def ebbinghaus_command(args) -> None:
    sub = getattr(args, "ebbinghaus_command", None)
    handlers = {"judge": _judge, "findings": _findings}
    handler = handlers.get(sub)
    if handler is None:
        _emit({"error": "choose a subcommand", "choices": sorted(handlers)})
        raise SystemExit(2)
    raise SystemExit(handler(args))


def register_cli(subparser) -> None:
    subs = subparser.add_subparsers(dest="ebbinghaus_command")

    judge = subs.add_parser(
        "judge",
        help="LLM-as-judge review: contradiction pairs and goal achievement flags",
        description=(
            "Evaluate recent memories against related memories with the configured "
            "model. Memories are never modified; flags go to the plugin-data "
            "judge_findings.db. Defaults to --estimate (no model calls)."
        ),
    )
    mode = judge.add_mutually_exclusive_group()
    mode.add_argument("--estimate", action="store_true", help="count candidates and planned calls only (default)")
    mode.add_argument(
        "--run", action="store_true",
        help="call the model (requires plugins.ebbinghaus.judge_enabled: true); memory text is sent to your provider",
    )
    judge.add_argument("--max-calls", type=int, default=None, help="cap below judge_max_calls for this run")
    judge.add_argument("--memory-id", type=int, action="append", help="judge specific memory ids (repeatable)")

    findings = subs.add_parser("findings", help="List recorded judge flags (ids and statuses only)")
    findings.add_argument("--limit", type=int, default=50)
    findings.add_argument("--state", default="open", help="review_state filter (default: open)")

    subparser.set_defaults(func=ebbinghaus_command)
