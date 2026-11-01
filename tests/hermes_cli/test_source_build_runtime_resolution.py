"""Source builds must retain the runtime selected by their managed environment."""

import os
from pathlib import Path

from hermes_cli import source_build


def test_source_script_uses_explicit_managed_path_not_ambient_path(tmp_path, monkeypatch):
    managed = tmp_path / "managed"
    ambient = tmp_path / "ambient"
    managed.mkdir()
    ambient.mkdir()
    name = "node.exe" if os.name == "nt" else "node"
    for directory in (managed, ambient):
        executable = directory / name
        executable.write_text("fixture", encoding="utf-8")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(ambient))
    calls = []
    monkeypatch.setattr(source_build, "run_in_custody", lambda *args, **kwargs: calls.append((args, kwargs)))
    env = {"PATH": str(managed)}

    source_build.run_source_script(tmp_path, "scripts/build/tui.mjs", "--no-install", env=env, label="fixture")

    args, kwargs = calls[0]
    assert Path(args[1][0]) == managed / name
    assert args[1][1:] == [str(tmp_path / "scripts/build/tui.mjs"), "--no-install"]
    assert kwargs["env"] is env
