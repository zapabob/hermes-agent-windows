"""
Voice push tool — synthesize text to speech and deliver to Discord / Telegram.

Uses the existing TTS tool (text_to_speech_tool) to generate audio, then
pushes the resulting audio file to the configured destination (Discord channel
and/or Telegram chat) as a voice message attachment.

Requirements
------------
- TTS provider must be available (Edge TTS by default; irodori TTS when the
  local server is running at http://127.0.0.1:8088 and configured).
- For Discord delivery: DISCORD_BOT_TOKEN must be set.
- For Telegram delivery: TELEGRAM_BOT_TOKEN must be set.

The TTS provider can be overridden per-call via the ``provider`` parameter.
To use irodori TTS with the Hakua voice, start the irodori TTS server and
configure it as a command provider in config.yaml under ``tts.providers.irodori``,
or rely on the default provider if that is how the local environment is set up.
"""

import json
import logging
import os
import tempfile
from typing import Any, Callable, Dict, Optional

from tools.discord_tool import _send_discord_voice
from tools.telegram_tool import _send_telegram_voice
from tools.tts_tool import text_to_speech_tool
from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)


def _voice_push(
    text: str,
    destinations: str = "",
    channel_id: str = "",
    chat_id: str = "",
    caption: str = "",
    provider: str = "",
    speed: float = 1.0,
    output_path: str = "",
    **_kwargs: Any,
) -> str:
    """Synthesize *text* to speech and push the audio to the requested destinations.

    Parameters
    ----------
    text:
        The message text to speak.
    destinations:
        Comma-separated list of destinations to push to. Recognized values
        are ``discord`` and ``telegram``. When empty, both are attempted
        if their credentials are available.
    channel_id:
        Discord channel ID (required when ``discord`` is in destinations).
    chat_id:
        Telegram chat ID (required when ``telegram`` is in destinations).
    caption:
        Optional caption prepended to the audio message on each platform.
    provider:
        Optional TTS provider override (e.g. ``irodori`` if configured).
    speed:
        Playback speed multiplier (0.25-4.0). Passed to the TTS tool.
    output_path:
        Optional custom path for the generated audio file. When omitted a
        temporary file is created and cleaned up after delivery.
    """
    if not text or not text.strip():
        return tool_error("text is required")

    try:
        tts_kwargs: Dict[str, Any] = {"text": text}
        if output_path:
            tts_kwargs["output_path"] = output_path
        if speed != 1.0:
            tts_kwargs["speed"] = speed
        if provider:
            tts_kwargs["provider"] = provider

        tts_result_raw = text_to_speech_tool(**tts_kwargs)
        tts_result = json.loads(tts_result_raw)
        if not tts_result.get("success"):
            return tool_error(f"TTS failed: {tts_result.get('error', 'unknown')}")

        file_path = tts_result.get("file_path")
        if not file_path or not os.path.isfile(file_path):
            return tool_error("TTS produced no usable audio file")

        created_temp = False
        if not output_path:
            created_temp = True

        use_discord = "discord" in destinations.lower().split(",") if destinations else False
        use_telegram = "telegram" in destinations.lower().split(",") if destinations else False

        if not destinations:
            # Auto-detect: send to whichever platform has credentials
            use_discord = bool(os.getenv("DISCORD_BOT_TOKEN"))
            use_telegram = bool(os.getenv("TELEGRAM_BOT_TOKEN"))

        results: list[Dict[str, Any]] = []

        if use_discord:
            if not channel_id:
                return tool_error("channel_id is required for Discord delivery")
            disc_result_raw = _send_discord_voice(
                token=os.environ["DISCORD_BOT_TOKEN"],
                channel_id=channel_id,
                file_path=file_path,
            )
            disc_result = json.loads(disc_result_raw)
            if not disc_result.get("success"):
                logger.warning("Discord voice push failed: %s", disc_result.get("error"))
            else:
                results.append({"platform": "discord", "result": disc_result})

        if use_telegram:
            if not chat_id:
                return tool_error("chat_id is required for Telegram delivery")
            tele_result_raw = _send_telegram_voice(
                token=os.environ["TELEGRAM_BOT_TOKEN"],
                chat_id=chat_id,
                file_path=file_path,
                caption=caption or None,
            )
            tele_result = json.loads(tele_result_raw)
            if not tele_result.get("success"):
                logger.warning("Telegram voice push failed: %s", tele_result.get("error"))
            else:
                results.append({"platform": "telegram", "result": tele_result})

        if not results:
            return tool_error("No destinations selected and no credentials available")

        return json.dumps(
            {
                "success": True,
                "file_path": file_path,
                "platforms": [r["platform"] for r in results],
                "details": results,
            },
            ensure_ascii=False,
        )

    except json.JSONDecodeError:
        return tool_error("Internal error: TTS tool returned invalid JSON")
    except Exception as e:
        logger.exception("voice_push failed")
        return tool_error(f"Unexpected error: {e}")
    finally:
        # Clean up temp file if we created one and it still exists
        if created_temp and output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass


_REGISTRY_DEFAULTS = {
    "text": "",
    "destinations": "",
    "channel_id": "",
    "chat_id": "",
    "caption": "",
    "provider": "",
    "speed": 1.0,
    "output_path": "",
}


def _make_voice_push_handler(handler_fn):
    """Create a registry-compatible handler lambda for voice_push."""
    return lambda args, **kw: handler_fn(
        **{k: args.get(k, v) for k, v in _REGISTRY_DEFAULTS.items()},
    )


def _get_voice_push_schema() -> Optional[Dict[str, Any]]:
    """Build the voice_push tool schema."""
    return {
        "name": "voice_push",
        "description": (
            "Synthesize text to speech via the configured TTS provider and push the "
            "audio to Discord and/or Telegram as a voice message. "
            "Requires DISCORD_BOT_TOKEN and/or TELEGRAM_BOT_TOKEN. "
            "When no destinations are specified, it auto-selects whichever platform "
            "has credentials available. "
            "To use irodori TTS with the Hakua voice, configure the irodori provider "
            "in config.yaml (tts.providers.irodori) or ensure it is the default."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The message text to speak.",
                },
                "destinations": {
                    "type": "string",
                    "description": (
                        "Comma-separated list of destinations: 'discord', 'telegram', "
                        "or empty to auto-detect from available credentials."
                    ),
                },
                "channel_id": {
                    "type": "string",
                    "description": "Discord channel ID (required if sending to Discord).",
                },
                "chat_id": {
                    "type": "string",
                    "description": "Telegram chat ID (required if sending to Telegram).",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional caption for the voice message.",
                },
                "provider": {
                    "type": "string",
                    "description": "Optional TTS provider override (e.g. 'irodori' for Hakua voice).",
                },
                "speed": {
                    "type": "number",
                    "description": "Playback speed multiplier (0.25-4.0, default 1.0).",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional custom path for the generated audio file.",
                },
            },
            "required": ["text"],
        },
    }


def check_voice_push_requirements() -> bool:
    """At least one platform credential must be available."""
    return bool(os.getenv("DISCORD_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN"))


def voice_push_handler(action: str, **kwargs) -> str:
    """Handler entry point for the voice_push tool."""
    _ = action
    return _voice_push(**kwargs)


_VOICE_PUSH_TOOLS: list[tuple[str, dict[str, Any], Callable[..., str]]] = [
    (
        "voice_push",
        _get_voice_push_schema(),
        voice_push_handler,
    ),
]


def get_tool_definitions() -> list[dict[str, Any]]:
    """Return tool definitions for the voice_push toolset.

    This is the canonical surface used by the model/tool-discovery layer.
    """
    out: list[dict[str, Any]] = []
    for _name, _schema, _handler in _VOICE_PUSH_TOOLS:
        defn: dict[str, Any] = dict(_schema)
        defn["handler"] = _handler
        out.append(defn)
    return out


registry.register(
    name="voice_push",
    toolset="voice_push",
    schema=_get_voice_push_schema(),
    handler=_make_voice_push_handler(voice_push_handler),
    check_fn=check_voice_push_requirements,
    requires_env=["DISCORD_BOT_TOKEN", "TELEGRAM_BOT_TOKEN"],
)
