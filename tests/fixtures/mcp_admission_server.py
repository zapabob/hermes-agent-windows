"""Owned real MCP 2 server for Windows stdio and loopback HTTP qualification.

No external services, credentials, shell commands or production HOME access.
Only an owned JSONL effect log is written. Stdout belongs to stdio transport.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time

import psutil
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=("stdio", "http"), required=True)
    parser.add_argument("--effects", type=Path, required=True)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    effect_path = args.effects.resolve()
    owned_root = args.task_root.resolve()
    if owned_root.name != "mcp-admission-owned" or not Path(__file__).resolve().is_relative_to(owned_root):
        raise ValueError("Server script must be inside the task's owned temp directory")
    if not effect_path.is_relative_to(owned_root):
        raise ValueError("Effects must stay under this task's owned temp directory")
    if args.transport == "http" and not 0 < args.port < 65536:
        raise ValueError("Loopback HTTP requires an explicit owned port")

    def effect(operation, **fields):
        row = {"operation": operation, "pid": os.getpid(), "monotonic": time.monotonic(), **fields}
        with effect_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    async def list_tools(ctx, params):
        effect("list_tools")
        return types.ListToolsResult(tools=[types.Tool(
            name="write_sentinel", description="Write a nonce to the owned effect log.",
            input_schema={"type": "object", "properties": {
                "nonce": {"type": "string"}, "delay": {"type": "number", "minimum": 0, "maximum": 5}},
                "required": ["nonce"]})])

    async def call_tool(ctx, params):
        arguments = params.arguments or {}
        nonce = arguments["nonce"]
        delay = float(arguments.get("delay", 0))
        if not 0 <= delay <= 5:
            raise ValueError("Fixture delay exceeds its bounded range")
        effect("tool_begin", nonce=nonce)
        completed = False
        try:
            await asyncio.sleep(delay)
            effect("tool_effect", nonce=nonce)
            completed = True
            return types.CallToolResult(content=[types.TextContent(type="text", text="所有済み作用:" + nonce)])
        finally:
            if not completed:
                effect("tool_cancelled", nonce=nonce)

    async def list_resources(ctx, params):
        effect("list_resources")
        return types.ListResourcesResult(resources=[types.Resource(
            name="owned-resource", uri="owned://sentinel", description="Owned Japanese resource.")])

    async def read_resource(ctx, params):
        effect("read_resource", uri=str(params.uri))
        return types.ReadResourceResult(contents=[types.TextResourceContents(uri=str(params.uri), text="所有済み資源")])

    async def list_prompts(ctx, params):
        effect("list_prompts")
        return types.ListPromptsResult(prompts=[types.Prompt(name="owned-prompt", description="Owned prompt.")])

    async def get_prompt(ctx, params):
        effect("get_prompt", name=params.name)
        return types.GetPromptResult(messages=[types.PromptMessage(
            role="user", content=types.TextContent(type="text", text="所有済みプロンプト"))])

    server = Server("owned-m02-native", on_list_tools=list_tools, on_call_tool=call_tool,
                    on_list_resources=list_resources, on_read_resource=read_resource,
                    on_list_prompts=list_prompts, on_get_prompt=get_prompt)
    process = psutil.Process()
    effect("boot", transport=args.transport, identity={
        "pid": process.pid, "created": process.create_time(), "exe": process.exe(), "argv": process.cmdline()})
    if args.transport == "stdio":
        async def serve():
            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())
        asyncio.run(serve())
    else:
        import uvicorn
        app = server.streamable_http_app(host="127.0.0.1")
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
