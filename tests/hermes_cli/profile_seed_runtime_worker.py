"""Fresh native process for profile route acceptance, with a real CLI/agent/SDK."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys


def main():
    manifest_path = Path(sys.argv[1]).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    home = Path(manifest["profile_home"]).resolve()
    assert home.is_relative_to(manifest_path.parent)
    assert Path(os.environ["HERMES_HOME"]).resolve() == home
    violations = []
    allowed = ("127.0.0.1", manifest["port"])
    real_connect, real_connect_ex, real_lookup = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def validate(address):
        if not isinstance(address, tuple) or address[:2] != allowed:
            violations.append(str(address))
            raise AssertionError(f"Only the owned profile model peer is allowed: {address!r}")

    def connect(sock, address):
        validate(address)
        return real_connect(sock, address)

    def lookup(host, port, *args, **kwargs):
        validate((host, int(port)))
        return real_lookup(host, port, *args, **kwargs)

    def connect_ex(sock, address):
        validate(address)
        return real_connect_ex(sock, address)

    def audit(event, _args):
        if event in {"winreg.SetValue", "winreg.CreateKey", "winreg.DeleteKey", "winreg.DeleteValue"}:
            violations.append(event)
            raise AssertionError("The profile test forbids OS registry writes")

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = lookup
    sys.addaudithook(audit)
    from hermes_cli import _install_repair
    _install_repair.ensure_windows_bin_launchers = lambda *_a, **_kw: None
    import cli

    shell = cli.HermesCLI(toolsets=[], max_turns=2, compact=True, ignore_rules=True,
                          reasoning="high", resume=manifest.get("resume"))
    shell.streaming_enabled = False
    shell._single_query_mode = True
    try:
        answer = shell.chat(manifest["prompt"])
        assert answer == "Owned answer: " + manifest["prompt"], answer
        messages = shell._session_db.get_messages(shell.agent.session_id)
        report = {"pid": os.getpid(), "session_id": shell.agent.session_id, "model": shell.model,
                  "provider": shell.provider, "base_url": shell.base_url, "answer": answer,
                  "users": [m["content"] for m in messages if m["role"] == "user"], "violations": violations}
    finally:
        cleanup_errors = []
        for close in [shell.agent.close if shell.agent is not None else lambda: None,
                      cli._run_cleanup, shell._session_db.close if shell._session_db is not None else lambda: None]:
            try:
                close()
            except BaseException as exc:
                cleanup_errors.append(repr(exc))
        assert not cleanup_errors, cleanup_errors
    assert not violations, violations
    Path(manifest["report_path"]).write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
