"""Missing TUI recovery must retain the shared internal Git authority."""
import shlex
import shutil
import subprocess
import sys

import pytest

from hermes_cli import main
from hermes_cli._subprocess_compat import noninteractive_git_env


@pytest.fixture
def tracked_workspace(tmp_path):
    git = shutil.which("git")
    assert git, "Native Git is required"
    repo = tmp_path / "owned-repo"
    repo.mkdir()

    def setup(*args):
        return subprocess.run([git, *args], cwd=repo, env=noninteractive_git_env(),
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", timeout=10, check=True)

    setup("init", "--initial-branch=fixture")
    setup("config", "user.name", "Fixture")
    setup("config", "user.email", "fixture@example.invalid")
    workspace = repo / "ui-tui"
    workspace.mkdir()
    (workspace / "entry.txt").write_bytes(b"owned tracked entry\n")
    (repo / ".gitattributes").write_text("ui-tui/*.txt -text filter=fixture\n", encoding="utf-8")
    setup("add", ".")
    setup("commit", "-m", "Owned TUI workspace")
    return repo, workspace, setup


def remove_workspace(workspace):
    (workspace / "entry.txt").unlink()
    workspace.rmdir()


def test_valid_restore_recovers_tracked_bytes(tracked_workspace):
    _, workspace, _ = tracked_workspace
    remove_workspace(workspace)
    assert main._restore_tui_workspace(workspace)
    assert (workspace / "entry.txt").read_bytes() == b"owned tracked entry\n"


def test_restore_neutralizes_repository_smudge(tracked_workspace, tmp_path):
    repo, workspace, setup = tracked_workspace
    marker = tmp_path / "smudge-executed"
    script = tmp_path / "owned-smudge.py"
    script.write_text("import pathlib,sys\n"
                      f"pathlib.Path({str(marker)!r}).write_text('OWNED_SENTINEL',encoding='utf-8')\n"
                      "sys.stdout.buffer.write(sys.stdin.buffer.read())\n", encoding="utf-8")
    command = " ".join(shlex.quote(value.replace("\\", "/"))
                       for value in (sys.executable, "-I", str(script)))
    setup("config", "filter.fixture.smudge", command)
    before = (repo / ".git" / "config").read_bytes()
    remove_workspace(workspace)
    assert main._restore_tui_workspace(workspace)
    assert not marker.exists()
    assert (workspace / "entry.txt").read_bytes() == b"owned tracked entry\n"
    assert (repo / ".git" / "config").read_bytes() == before


def test_discovery_refusal_leaves_workspace_missing(tracked_workspace):
    repo, workspace, setup = tracked_workspace
    invalid = repo / ".git" / "inactive-owned-config"
    invalid.write_text("[invalid\n", encoding="utf-8")
    setup("config", "includeIf.gitdir:never-active.path", str(invalid))
    before = invalid.read_bytes()
    remove_workspace(workspace)
    assert not main._restore_tui_workspace(workspace)
    assert not workspace.exists()
    assert invalid.read_bytes() == before


def test_failed_restore_cannot_report_existing_directory_success(tracked_workspace, monkeypatch):
    _, workspace, _ = tracked_workspace
    import hermes_cli._subprocess_compat as policy
    failure = subprocess.CompletedProcess(["git", "restore"], 128, "", "owned failure")
    monkeypatch.setattr(main.subprocess, "run", lambda *a, **kw: failure)
    monkeypatch.setattr(policy, "run_internal_git", lambda *a, **kw: failure)
    assert not main._restore_tui_workspace(workspace)
    assert (workspace / "entry.txt").read_bytes() == b"owned tracked entry\n"


def test_missing_git_is_a_recoverable_failure(tracked_workspace, monkeypatch):
    _, workspace, _ = tracked_workspace
    monkeypatch.setattr(main.shutil, "which", lambda *a, **kw: None)
    remove_workspace(workspace)
    assert not main._restore_tui_workspace(workspace)
    assert not workspace.exists()
