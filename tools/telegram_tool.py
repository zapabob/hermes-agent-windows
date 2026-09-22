"""
Telegram voice message sending tool.

Provides the agent with the ability to send voice/audio messages
to Telegram chats when running on the Telegram gateway or as a standalone tool.
Uses Telegram Bot API directly with the bot token.
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def _get_bot_token() -> Optional[str]:
    """Resolve the Telegram bot token from environment."""
    return (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() or None


def _guess_audio_mime(path: str) -> str:
    """Best-effort MIME type for audio file."""
    ext = os.path.splitext(path)[1].lower()
    mimes = {
        ".ogg": "audio/ogg",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".webm": "audio/webm",
    }
    return mimes.get(ext, "audio/ogg")


def _send_telegram_voice(
    token: str,
    chat_id: str,
    file_path: str,
    caption: Optional[str] = None,
    **_kwargs: Any,
) -> str:
    """Send a voice/audio file to a Telegram chat.

    Uses the sendVoice Bot API method.
    """
    if not os.path.isfile(file_path):
        return tool_error(f"File not found: {file_path}")

    file_size = os.path.getsize(file_path)
    if file_size > 50 * 1024 * 1024:  # Telegram 50MB limit for voice
        return tool_error(
            f"Audio file too large: {file_size} bytes (limit 52,428,800 bytes)."
        )

    url = f"{TELEGRAM_API_BASE}{token}/sendVoice"
    mime_type = _guess_audio_mime(file_path)

    boundary = f"------------------------{abs(hash(file_path)) % 10**10:010x}"
    body = bytearray()

    # Build multipart form data
    # Attach the audio file
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    body += b"--" + boundary.encode("utf-8") + b"\r\n"
    body += (
        b"Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n"
        + chat_id.encode("utf-8")
        + b"\r\n"
    )

    if caption:
        body += (
            b"--" + boundary.encode("utf-8") + b"\r\n"
            b"Content-Disposition: form-data; name=\"caption\"\r\n\r\n"
            + caption.encode("utf-8")
            + b"\r\n"
        )

    body += (
        b"--" + boundary.encode("utf-8") + b"\r\n"
        b"Content-Disposition: form-data; name=\"voice\"; filename=\"voice"
        + os.path.basename(file_path).encode("utf-8")
        + b"\"\r\n"
        b"Content-Type: " + mime_type.encode("utf-8") + b"\r\n\r\n"
    )
    body += file_bytes + b"\r\n"
    body += b"--" + boundary.encode("utf-8") + b"--\r\n"

    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "Hermes-Agent (https://github.com/NousResearch/hermes-agent)",
    }

    req = urllib.request.Request(url, data=bytes(body), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_body = resp.read()
            result = json.loads(response_body.decode("utf-8"))
            if not result.get("ok"):
                return tool_error(f"Telegram API error: {result.get('description', 'unknown')}")
            voice_msg = result.get("voice", {})
            return json.dumps(
                {
                    "success": True,
                    "message_id": result.get("message_id"),
                    "chat_id": result.get("chat", {}).get("id"),
                    "voice_duration": voice_msg.get("duration"),
                }
            )
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        return tool_error(f"Telegram API HTTP {e.code}: {error_body}")
    except json.JSONDecodeError:
        return tool_error("Telegram API returned invalid JSON")


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

_TELEGRAM_ACTIONS = {
    "send_voice": _send_telegram_voice,
}

_TELEGRAM_ACTION_MANIFEST = [
    ("send_voice", "(chat_id, file_path[, caption])", "send an audio file as a voice message"),
]

_SCHEMA_PROPERTIES = {
    "action": {
        "type": "string",
        "enum": list(_TELEGRAM_ACTIONS.keys()),
    },
    "chat_id": {
        "type": "string",
        "description": "Telegram chat ID (numeric or @username for public channels).",
    },
    "file_path": {
        "type": "string",
        "description": "Path to the audio file to send as a voice message.",
    },
    "caption": {
        "type": "string",
        "description": "Optional caption for the voice message.",
    },
}


def _get_dynamic_schema() -> Optional[Dict[str, Any]]:
    token = _get_bot_token()
    if not token:
        return None

    actions = list(_TELEGRAM_ACTIONS.keys())
    if not actions:
        return None

    manifest_lines = [
        f"  {name}{sig}  — {desc}"
        for name, sig, desc in _TELEGRAM_ACTION_MANIFEST
    ]
    manifest_block = "\n".join(manifest_lines)

    description = (
        "Send voice/audio messages to Telegram chats.\n\n"
        "Available actions:\n"
        f"{manifest_block}\n\n"
        "Requires TELEGRAM_BOT_TOKEN environment variable."
    )

    return {
        "name": "telegram",
        "description": description,
        "parameters": {
            "type": "object",
            "properties": _SCHEMA_PROPERTIES,
            "required": ["action", "chat_id", "file_path"],
        },
    }


# Static schema used for registration when dynamic schema is unavailable
_STATIC_SCHEMA = {
    "name": "telegram",
    "description": (
        "Send voice/audio messages to Telegram chats.\n\n"
        "Available actions:\n"
        "  send_voice(chatto_id, file_path[, caption])  — send an audio file as a voice message\n\n"
        "Requires TELEGRAM_BOT_TOKEN environment variable. "
        "When the token is not configured, the tool is hidden from the schema."
    ),
    "parameters": {
        "type": "object",
        "properties": _SCHEMA_PROPERTIES,
        "required": ["action", "chat_id", "file_path"],
    },
}


def _run_telegram_action(action: str, **kwargs) -> str:
    """Execute a Telegram action."""
    token = _get_bot_token()
    if not token:
        return tool_error("TELEGRAM_BOT_TOKEN not configured.")

    action_fn = _TELEGRAM_ACTIONS.get(action)
    if not action_fn:
        return tool_error(
            f"Unknown action: {action}",
            available_actions=list(_TELEGRAM_ACTIONS.keys()),
        )

    try:
        return action_fn(token=token, **kwargs)
    except Exception as e:
        logger.exception("Unexpected error in telegram action '%s'", action)
        return tool_error(f"Unexpected error: {e}")


def telegram_handler(action: str, **kwargs) -> str:
    """Execute a Telegram action (standalone tool handler)."""
    return _run_telegram_action(action, **kwargs)


def check_telegram_tool_requirements() -> bool:
    """Tool is available only when a Telegram bot token is configured."""
    return bool(_get_bot_token())


registry.register(
    name="telegram",
    toolset="telegram",
    schema=_STATIC_SCHEMA,
    handler=lambda args, **kw: telegram_handler(
        action=args.get("action", ""),
        chat_id=args.get("chat_id", ""),
        file_path=args.get("file_path", ""),
        caption=args.get("caption"),
    ),
    check_fn=check_telegram_tool_requirements,
    requires_env=["TELEGRAM_BOT_TOKEN"],
)
