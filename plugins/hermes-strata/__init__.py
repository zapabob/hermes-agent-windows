"""hermes-strata — Strata local inference & Hakua persistent memory plugin for Hermes Agent.

Exposes native inference tools to offload large model computation (DeepSeek MLA, Spin(8), GGUF)
to the local Strata engine, and synchronizes Hakua SOUL.md / MEMORY.md long-term memory.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .core import (
    append_memory_entry,
    build_system_context,
    inspect_gguf_file,
    probe_strata_server,
    read_memory_entries,
    read_soul_directives,
    resolve_memory_path,
    resolve_soul_path,
    run_strata_inference,
)

logger = logging.getLogger(__name__)


def _status_handler(_: Any = None, **__: Any) -> str:
    """Handle strata_status tool invocation."""
    status = probe_strata_server()
    return json.dumps(status, ensure_ascii=False, indent=2)


def _infer_handler(args: Any = None, **__: Any) -> str:
    """Handle strata_infer tool invocation."""
    data = args if isinstance(args, dict) else {}
    prompt = str(data.get("prompt") or "")
    model = data.get("model")
    system_prompt = data.get("system_prompt")
    temperature = float(data.get("temperature", 0.7))
    max_tokens = int(data.get("max_tokens", 4096))
    thinking = bool(data.get("thinking", True))
    inject_memory = bool(data.get("inject_memory", False))

    result = run_strata_inference(
        prompt=prompt,
        model=model,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        thinking=thinking,
        inject_memory=inject_memory,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


def _memory_handler(args: Any = None, **__: Any) -> str:
    """Handle strata_memory_sync tool invocation."""
    data = args if isinstance(args, dict) else {}
    action = str(data.get("action") or "read").lower()
    entry = str(data.get("entry") or "")
    max_entries = int(data.get("max_entries", 10))

    if action == "append":
        if not entry:
            return json.dumps({"success": False, "error": "entry parameter is required for append"}, ensure_ascii=False)
        ok = append_memory_entry(entry)
        return json.dumps({"success": ok, "appended_entry": entry, "memory_path": str(resolve_memory_path())}, ensure_ascii=False, indent=2)

    elif action == "context":
        ctx_str = build_system_context(include_soul=True, include_memory=True, max_memories=max_entries)
        return json.dumps({"success": True, "context": ctx_str}, ensure_ascii=False, indent=2)

    elif action == "stats":
        mem_path = resolve_memory_path()
        soul_path = resolve_soul_path()
        entries = read_memory_entries(max_entries=1000)
        return json.dumps(
            {
                "success": True,
                "soul_file": str(soul_path) if soul_path else None,
                "soul_exists": soul_path is not None,
                "memory_file": str(mem_path),
                "memory_exists": mem_path.exists(),
                "total_memory_entries": len(entries),
                "memory_file_size_bytes": mem_path.stat().st_size if mem_path.exists() else 0,
            },
            ensure_ascii=False,
            indent=2,
        )

    else:  # "read"
        memories = read_memory_entries(max_entries=max_entries)
        soul = read_soul_directives()
        soul_excerpt = "\n".join(soul.splitlines()[:30]) if soul else ""
        return json.dumps(
            {
                "success": True,
                "soul_directives_summary": soul_excerpt,
                "recent_memories": memories,
                "entries_count": len(memories),
            },
            ensure_ascii=False,
            indent=2,
        )


def _inspect_gguf_handler(args: Any = None, **__: Any) -> str:
    """Handle strata_inspect_gguf tool invocation."""
    data = args if isinstance(args, dict) else {}
    path = str(data.get("path") or "")
    if not path:
        return json.dumps({"valid": False, "error": "path parameter is required"}, ensure_ascii=False)
    result = inspect_gguf_file(path)
    return json.dumps(result, ensure_ascii=False, indent=2)


def register(ctx: Any) -> None:
    """Register Strata local inference & memory tools in Hermes Agent."""
    ctx.register_tool(
        name="strata_status",
        toolset="strata",
        schema={"type": "object", "properties": {}},
        handler=_status_handler,
        check_fn=lambda: True,
        description="Probe local Strata inference server (DeepSeek MLA, Spin(8), 32GB zero-VRAM drafting) status and hardware configuration.",
    )

    ctx.register_tool(
        name="strata_infer",
        toolset="strata",
        schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "prompt": {"type": "string", "description": "User prompt or instruction to execute."},
                "model": {"type": "string", "description": "Model ID to query (default: deepseek-v4.1-flash, or qwen3.8-flash-next)."},
                "system_prompt": {"type": "string", "description": "Optional system prompt override."},
                "temperature": {"type": "number", "minimum": 0.0, "maximum": 2.0, "description": "Sampling temperature (default 0.7)."},
                "max_tokens": {"type": "integer", "minimum": 1, "maximum": 32768, "description": "Max tokens to generate (default 4096)."},
                "thinking": {"type": "boolean", "description": "Enable DeepSeek reasoning/thinking mode (default true)."},
                "inject_memory": {"type": "boolean", "description": "Inject Hakua SOUL.md directives & MEMORY.md recall into system prompt (default false)."},
            },
            "required": ["prompt"],
        },
        handler=_infer_handler,
        check_fn=lambda: True,
        description="Execute high-throughput inference via local Strata engine, returning content, reasoning thoughts, and token usage.",
    )

    ctx.register_tool(
        name="strata_memory_sync",
        toolset="strata",
        schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "append", "context", "stats"],
                    "description": "Operation: 'read' (fetch SOUL.md & recent memories), 'append' (record new memory entry), 'context' (build prompt context), 'stats' (memory storage metrics).",
                },
                "entry": {"type": "string", "description": "Text to record when action is 'append'."},
                "max_entries": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Number of memory entries to fetch (default 10)."},
            },
        },
        handler=_memory_handler,
        check_fn=lambda: True,
        description="Synchronize and query Hakua SOUL.md core alignment and MEMORY.md long-term memories.",
    )

    ctx.register_tool(
        name="strata_inspect_gguf",
        toolset="strata",
        schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to a .gguf file to inspect."},
            },
            "required": ["path"],
        },
        handler=_inspect_gguf_handler,
        check_fn=lambda: True,
        description="Validate and inspect arbitrary user GGUF model files against local RTX 5060 Ti 16GB + 32GB RAM hardware profiles.",
    )
