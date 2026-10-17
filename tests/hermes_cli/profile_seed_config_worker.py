"""Owned subprocess exercising the existing atomic configuration writer."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys


def main():
    manifest_path = Path(sys.argv[1]).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    home = Path(manifest["home"]).resolve()
    assert home.is_relative_to(manifest_path.parent)
    assert Path(os.environ["HERMES_HOME"]).resolve() == home
    violations = []

    def deny_network(*_args, **_kwargs):
        violations.append("network attempt")
        raise AssertionError("The owned configuration writer is offline")

    def audit(event, _args):
        if event in {"winreg.SetValue", "winreg.CreateKey", "winreg.DeleteKey", "winreg.DeleteValue"}:
            violations.append(event)
            raise AssertionError("The owned configuration writer forbids registry mutation")

    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.getaddrinfo = deny_network
    sys.addaudithook(audit)
    from hermes_cli import _install_repair
    _install_repair.ensure_windows_bin_launchers = lambda *_a, **_kw: None
    from hermes_cli.config import atomic_config_write
    from tools.mcp_oauth_state import oauth_state_lock

    # Announce readiness only after imports. The marker immediately before
    # acquiring the real process fence lets the parent observe contention.
    try:
        Path(manifest["ready"]).write_text("ready", encoding="utf-8")
        with oauth_state_lock(home):
            Path(manifest["acquired"]).write_text("acquired", encoding="utf-8")
            atomic_config_write(home / "config.yaml", manifest["config"])
    finally:
        (manifest_path.parent / "config-worker-audit.json").write_text(json.dumps({"violations": violations}), encoding="utf-8")
    assert not violations, violations


if __name__ == "__main__":
    main()
