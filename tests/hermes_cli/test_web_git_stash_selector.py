"""Dashboard stash apply/drop address entries by bare index, never ``stash@{N}``.

On native Windows the MSYS runtime re-parses git.exe's argv when the parent is a
non-MSYS process (python.exe) and strips the braces, so ``stash@{1}`` reaches git
as ``stash@1`` and is rejected (#87542).
"""

import subprocess

import pytest

from hermes_cli import web_git


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def repo_with_two_stashes(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    # A host-global core.autocrlf=true (Git for Windows default) leaves the tree looking dirty
    # after `stash push`, which would make the apply refuse for reasons unrelated to selectors.
    _git(tmp_path, "config", "core.autocrlf", "false")
    (tmp_path / "f.txt").write_text("v1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    (tmp_path / "f.txt").write_text("older\n", encoding="utf-8")
    _git(tmp_path, "stash", "push", "-q", "-m", "older")
    older = _git(tmp_path, "rev-parse", "refs/stash").stdout.strip()
    (tmp_path / "f.txt").write_text("newer\n", encoding="utf-8")
    _git(tmp_path, "stash", "push", "-q", "-m", "newer")
    return tmp_path, older


@pytest.fixture
def git_argv(monkeypatch):
    log: list[list[str]] = []
    real_git = web_git._git

    def recording_git(cwd, args, **kwargs):
        log.append(list(args))
        return real_git(cwd, args, **kwargs)

    monkeypatch.setattr(web_git, "_git", recording_git)
    return log


def test_stash_drop_targets_the_indexed_entry_without_braces(repo_with_two_stashes, git_argv):
    repo, older = repo_with_two_stashes

    web_git.stash_drop(str(repo), 1)

    assert older not in _git(repo, "stash", "list", "--format=%H").stdout
    assert "newer" in _git(repo, "stash", "list").stdout
    assert not any("{" in arg or "}" in arg for argv in git_argv for arg in argv), git_argv


def test_stash_apply_targets_the_indexed_entry_without_braces(repo_with_two_stashes, git_argv):
    repo, _older = repo_with_two_stashes

    web_git.stash_apply(str(repo), 1)

    assert (repo / "f.txt").read_text(encoding="utf-8") == "older\n"
    assert not any("{" in arg or "}" in arg for argv in git_argv for arg in argv), git_argv
