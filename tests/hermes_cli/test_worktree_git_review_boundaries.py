"""Worktree setup must distinguish missing targets from policy refusals."""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import web_git
from hermes_cli._subprocess_compat import GitPolicyError


def test_missing_worktree_target_does_not_attempt_git_discovery(tmp_path, monkeypatch):
    run_git = Mock(side_effect=AssertionError("missing cwd must not launch Git"))
    monkeypatch.setattr(kb, "run_internal_git", run_git)

    assert kb._git_toplevel(tmp_path / "missing" / "target") is None
    run_git.assert_not_called()


def test_missing_worktree_target_resolves_from_existing_ancestor(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / ".worktrees" / "new-task"
    task = SimpleNamespace(id="new-task", workspace_path=str(target), branch_name="wt/new-task")
    inspected = []

    def run_git(args, cwd, *, timeout, check_policy):
        if not Path(cwd).is_dir():
            raise GitPolicyError("git filter discovery failed")
        assert args == ["rev-parse", "--show-toplevel"]
        assert timeout == 30 and check_policy is True
        inspected.append(Path(cwd))
        return subprocess.CompletedProcess(args, 0, str(repo.resolve()) + "\n", "")

    monkeypatch.setattr(kb, "run_internal_git", run_git)
    create = Mock()
    monkeypatch.setattr(kb, "_ensure_git_worktree", create)

    resolved, branch = kb._resolve_worktree_workspace(task)

    assert resolved == target
    assert branch == "wt/new-task"
    assert inspected == [repo]
    create.assert_called_once_with(repo.resolve(), target, branch)


def test_existing_repo_policy_refusal_is_not_non_repo(tmp_path, monkeypatch):
    refusal = GitPolicyError("git filter discovery failed")
    run_git = Mock(side_effect=refusal)
    monkeypatch.setattr(kb, "run_internal_git", run_git)

    with pytest.raises(GitPolicyError) as raised:
        kb._git_toplevel(tmp_path)

    assert raised.value is refusal
    run_git.assert_called_once()


def test_missing_target_ancestor_policy_refusal_prevents_creation(tmp_path, monkeypatch):
    target = tmp_path / ".worktrees" / "new-task"
    task = SimpleNamespace(id="new-task", workspace_path=str(target), branch_name="wt/new-task")
    refusal = GitPolicyError("git filter discovery failed")
    monkeypatch.setattr(kb, "run_internal_git", Mock(side_effect=refusal))
    create = Mock()
    monkeypatch.setattr(kb, "_ensure_git_worktree", create)

    with pytest.raises(GitPolicyError) as raised:
        kb._resolve_worktree_workspace(task)

    assert raised.value is refusal
    create.assert_not_called()


def test_web_plain_folder_initialization_keeps_policy_owner(tmp_path, monkeypatch):
    calls = []

    def run_git(args, cwd, *, timeout):
        assert cwd == str(tmp_path)
        assert timeout == web_git._GIT_TIMEOUT
        calls.append(args)
        if args == ["rev-parse", "--is-inside-work-tree"]:
            return subprocess.CompletedProcess(args, 128, "", "not a git repository")
        assert args == ["init"] or args == [
            "-c", "user.email=hermes@localhost", "-c", "user.name=Hermes",
            "commit", "--allow-empty", "-m", "Initial commit",
        ]
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(web_git, "run_internal_git", run_git)

    web_git._ensure_repo(str(tmp_path))

    assert len(calls) == 3
    assert calls[1] == ["init"]


def test_web_discovery_refusal_prevents_commit_and_worktree_creation(tmp_path, monkeypatch):
    calls = []

    def run_git(args, cwd, *, timeout):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, "", "git filter discovery failed")

    monkeypatch.setattr(web_git, "run_internal_git", run_git)

    with pytest.raises(RuntimeError, match="git filter discovery failed"):
        web_git.worktree_add(str(tmp_path), {"branch": "feature/plain"})

    assert calls[0] == ["rev-parse", "--is-inside-work-tree"]
    assert not any("commit" in args or "worktree" in args for args in calls)
