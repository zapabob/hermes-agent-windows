from __future__ import annotations

import json
from typing import Any

from .audio_buffer import _buffer_dir_from_config
from .audio_buffer import buffer_status as _buffer_status
from .audio_buffer import maybe_zip as _maybe_zip
from .core import IrodoriScriptTTSProvider, synthesize_text, status_payload


def _status_handler(_: Any = None, **__: Any) -> str:
    return json.dumps(status_payload(), ensure_ascii=False, indent=2)


def _synthesize_handler(
    text: str,
    output_path: str | None = None,
    voice: str | None = None,
    model: str | None = None,
    format: str | None = None,
    speed: float | None = None,
    **_: Any,
) -> str:
    result = synthesize_text(
        text=text,
        output_path=output_path,
        voice=voice,
        model=model,
        output_format=format,
        speed=speed,
        buffer=False,
    )
    # Temporary synthesis is owned by the caller; do not persist it in the
    # audio buffer. The normal GUI path removes it in a finally block.
    return json.dumps(result, ensure_ascii=False, indent=2)


def _buffer_zip_handler(_: Any = None, **__: Any) -> str:
    return json.dumps(_maybe_zip(_buffer_dir_from_config()), ensure_ascii=False, indent=2)


def _buffer_status_handler(_: Any = None, **__: Any) -> str:
    return json.dumps(_buffer_status(_buffer_dir_from_config()), ensure_ascii=False, indent=2)


def add_audio(path: str | Any = None) -> dict[str, Any]:
    if not path:
        return {"ok": False, "error": "path is required."}
    try:
        result = _add_audio(path)
        if isinstance(result, dict):
            return result
        if result is None:
            return {"ok": False, "error": "add_audio returned None"}
        return {"ok": True, "path": str(result)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def register(ctx) -> None:
    provider = IrodoriScriptTTSProvider()
    ctx.register_tts_provider(provider)

    ctx.register_tool(
        name="irodori_tts_status",
        toolset="tts",
        schema={
            "type": "object",
            "properties": {},
        },
        handler=_status_handler,
        check_fn=lambda: status_payload()["available"],
        description="Report local Irodori TTS script, server, and provider status.",
    )

    ctx.register_tool(
        name="irodori_tts_synthesize",
        toolset="tts",
        schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to synthesize.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional destination audio path.",
                },
                "voice": {
                    "type": "string",
                    "description": "Irodori voice id; defaults to none.",
                },
                "model": {
                    "type": "string",
                    "description": "Irodori model id.",
                },
                "format": {
                    "type": "string",
                    "description": "Audio format: wav, mp3, flac, opus, aac, or pcm.",
                },
                "speed": {
                    "type": "number",
                    "description": "Speech speed multiplier.",
                },
            },
            "required": ["text"],
        },
        handler=_synthesize_handler,
        check_fn=lambda: status_payload()["available"],
        description="Synthesize speech with local Irodori TTS through the Windows script harness.",
    )

    ctx.register_tool(
        name="irodori_tts_buffer_zip",
        toolset="tts",
        schema={
            "type": "object",
            "properties": {},
        },
        handler=_buffer_zip_handler,
        check_fn=lambda: status_payload()["available"],
        description="Zip buffered TTS wav files when the threshold is reached. Does not push to audio_ws.",
    )

    ctx.register_tool(
        name="irodori_tts_buffer_status",
        toolset="tts",
        schema={
            "type": "object",
            "properties": {},
        },
        handler=_buffer_status_handler,
        check_fn=lambda: status_payload()["available"],
        description="Show current irodori audio buffer backlog: files and bytes.",
    )

    ctx.register_tool(
        name="irodori_tts_buffer_add",
        toolset="tts",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Audio file to buffer."}
            },
            "required": ["path"],
        },
        handler=add_audio,
        check_fn=lambda: status_payload()["available"],
        description="Add an existing local audio file to the irodori TTS buffer.",
    )

    from .cli import register_cli

    ctx.register_cli_command(
        name="irodori-tts",
        help="Local Irodori TTS script backend",
        setup_fn=register_cli,
        description="Manage and invoke the local Irodori TTS script backend.",
    )
