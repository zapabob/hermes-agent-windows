from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .core import powershell_path, settings, status_payload, synthesize_text

logger = logging.getLogger(__name__)


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _start_server() -> int:
    cfg = settings()
    if not cfg.start_script.exists():
        print(f"Irodori start script not found: {cfg.start_script}")
        return 2
    ps = powershell_path()
    if not ps:
        print("PowerShell was not found on PATH.")
        return 2

    import subprocess

    try:
        endpoint = urlsplit(cfg.base_url)
        port = endpoint.port or 80
        if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Automatic server startup requires a local HTTP endpoint.")
    except ValueError as exc:
        logger.error("Invalid Irodori startup endpoint: %s", exc)
        return 2

    command = [
        ps,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(cfg.start_script),
        "-RepoDir",
        str(cfg.repo_dir),
        "-HostName",
        endpoint.hostname,
        "-Port",
        str(port),
    ]
    completed = subprocess.run(
        command,
        cwd=str(cfg.repo_dir),
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode


def register_cli(subparser) -> None:
    actions = subparser.add_subparsers(dest="irodori_tts_action")

    status_parser = actions.add_parser("status", help="Show provider and server status.")

    start_parser = actions.add_parser("start", help="Start the local Irodori server.")

    synth_parser = actions.add_parser("synthesize", help="Synthesize speech through the script backend.")
    synth_parser.add_argument("--text", help="Text to synthesize.")
    synth_parser.add_argument("--input-path", help="Read text from a UTF-8 file.")
    synth_parser.add_argument("--output-path", help="Destination audio path.")
    synth_parser.add_argument("--format", choices=["wav", "mp3", "flac", "opus", "aac", "pcm"], default="wav")
    synth_parser.add_argument("--voice", default=None)
    synth_parser.add_argument("--model", default=None)
    synth_parser.add_argument("--speed", type=float, default=None)
    subparser.set_defaults(func=irodori_tts_command)


def irodori_tts_command(args: Any) -> int:
    action = getattr(args, "irodori_tts_action", None)
    if action == "status":
        return _cmd_status(args)
    if action == "start":
        return _cmd_start(args)
    if action == "synthesize":
        return _cmd_synthesize(args)
    print("usage: hermes irodori-tts {status,start,synthesize}")
    return 2


def _cmd_status(args: Any) -> int:
    _print_json(status_payload())
    return 0


def _cmd_start(args: Any) -> int:
    return _start_server()


def _cmd_synthesize(args: Any) -> int:
    if args.input_path:
        text = Path(args.input_path).read_text(encoding="utf-8")
    else:
        text = args.text
    if not text:
        print("Provide --text or --input-path.")
        return 2

    result = synthesize_text(
        text=text,
        output_path=args.output_path,
        voice=args.voice,
        model=args.model,
        output_format=args.format,
        speed=args.speed,
    )
    _print_json(result)
    return 0
