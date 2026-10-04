"""Owned-repository updater contracts; never invoke cmd_update or infrastructure."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_cli import _subprocess_compat as compat
from hermes_cli import update_cmd as update


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git = shutil.which("git")
    assert git
    root = tmp_path / "repo with spaces"
    root.mkdir()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    def raw(*args):
        return subprocess.run([git, *args], cwd=root, check=True, capture_output=True,
                              text=True, encoding="utf-8", timeout=10,
                              creationflags=compat.windows_hide_flags())
    raw("init")
    raw("config", "user.name", "Owned fixture")
    raw("config", "user.email", "fixture@example.invalid")
    raw("config", "core.autocrlf", "false")
    (root / "package-lock.json").write_bytes(b"original\n")
    (root / ".gitattributes").write_text("package-lock.json filter=fixture\n", encoding="utf-8")
    raw("add", "--", ".")
    raw("commit", "-m", "owned baseline")
    return root, git, raw


def install_filter(repo, tmp_path, kind):
    root, git, raw = repo
    marker = tmp_path / (kind + "-executed")
    script = tmp_path / (kind + ".py")
    script.write_text("import pathlib,sys\npathlib.Path(" + repr(str(marker)) + ").write_text('executed')\n"
                      "sys.stdout.buffer.write(sys.stdin.buffer.read())\n", encoding="utf-8")
    command = '"' + sys.executable.replace("\\", "/") + '" "' + str(script).replace("\\", "/") + '"'
    raw("config", "filter.fixture." + kind, command)
    return marker


@pytest.mark.parametrize("kind", ["clean", "smudge"])
def test_lockfile_cleanup_never_executes_repo_filter(repo, tmp_path, kind):
    root, git, raw = repo
    marker = install_filter(repo, tmp_path, kind)
    (root / "package-lock.json").write_bytes(b"changed\n")
    update._discard_lockfile_churn([git], root)
    assert not marker.exists()
    assert (root / "package-lock.json").read_bytes() == b"original\n"


@pytest.mark.parametrize("owner", ["_get_origin_url", "_capture_head_sha", "_discard_lockfile_churn", "_normalize_managed_eol", "_branch_head_label"])
def test_normal_readers_and_cleanup_propagate_policy_refusal(repo, tmp_path, owner):
    root, git, raw = repo
    nested = tmp_path / "inactive-config"
    nested.write_text('[include]\npath = another-file\n', encoding="utf-8")
    raw("config", "includeIf.gitdir:never-matches.path", str(nested))
    before = (root / ".git/config").read_bytes(), (root / "package-lock.json").read_bytes()
    with pytest.raises(compat.GitPolicyError):
        getattr(update, owner)([git], root)
    assert before == ((root / ".git/config").read_bytes(), (root / "package-lock.json").read_bytes())


def test_failed_lockfile_checkout_is_not_reported_as_discarded(repo, monkeypatch, capsys):
    root, git, raw = repo
    (root / "package-lock.json").write_bytes(b"keep this\n")
    original = subprocess.run
    def fail_checkout(argv, *args, **kwargs):
        if "checkout" in argv:
            return subprocess.CompletedProcess(argv, 124, "", "owned injected timeout")
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", fail_checkout)
    original_bounded = compat.bounded_probe_run
    def fail_bounded(argv, **kwargs):
        if "checkout" in argv:
            return None
        return original_bounded(argv, **kwargs)
    monkeypatch.setattr(compat, "bounded_probe_run", fail_bounded)
    with pytest.raises(Exception):
        update._discard_lockfile_churn([git], root)
    assert "Discarded" not in capsys.readouterr().out
    assert (root / "package-lock.json").read_bytes() == b"keep this\n"


def test_normal_adapter_is_bounded_and_preserves_windows_git_selection(repo, monkeypatch):
    root, git, raw = repo
    seen = []
    def owned_run(args, cwd, **kwargs):
        seen.append((args, cwd, kwargs))
        return subprocess.CompletedProcess([git, *args], 0, b"ok\n", b"")
    monkeypatch.setattr(compat, "run_internal_git", owned_run)
    result = update._run_update_git([git, "-c", "windows.appendAtomically=false", "status"], cwd=root)
    assert result.stdout == "ok\n"
    args, cwd, kw = seen[0]
    assert cwd == root and kw["git_bin"] == git and kw["check_policy"] is True
    assert kw["binary_output"] is True and 0 < kw["max_output_bytes"] <= 8 * 1024 * 1024
    assert 0 < kw["timeout"] <= 30 and args[:2] == ["-c", "windows.appendAtomically=false"]


def test_bounded_failure_is_not_a_zip_fallback(repo, monkeypatch):
    root, git, raw = repo
    monkeypatch.setattr(compat, "run_internal_git", lambda args, cwd, **kw:
                        subprocess.CompletedProcess([git, *args], 124, b"", b"timed out"))
    with pytest.raises(update._UpdateGitExecutionError) as failure:
        update._run_update_git([git, "merge", "--ff-only", "origin/main"], cwd=root)
    assert not update._should_zip_fallback_on_update_error(failure.value)


@pytest.mark.parametrize("operation", ["checkout", "merge", "reset"])
def test_normal_mutation_neutralizes_filter_and_retains_saved_stash(repo, tmp_path, operation):
    root, git, raw = repo
    base = raw("branch", "--show-current").stdout.strip()
    raw("checkout", "-b", "next")
    (root / "package-lock.json").write_bytes(b"next content\n")
    raw("add", "--", "package-lock.json")
    raw("commit", "-m", "next owned content")
    raw("checkout", base)
    (root / "package-lock.json").write_bytes(b"saved local content\n")
    stash = update._stash_local_changes_if_needed([git], root)
    assert stash and raw("rev-parse", "refs/stash").stdout.strip() == stash
    marker = install_filter(repo, tmp_path, "smudge")
    args = {"checkout": ["checkout", "next"], "merge": ["merge", "--ff-only", "next"],
            "reset": ["reset", "--hard", "next"]}[operation]
    result = update._run_update_git([git, *args], cwd=root, check=True)
    assert result.returncode == 0 and not marker.exists()
    assert (root / "package-lock.json").read_bytes() == b"next content\n"
    assert raw("rev-parse", "refs/stash").stdout.strip() == stash
    assert "saved local content" in raw("show", stash + ":package-lock.json").stdout


@pytest.mark.parametrize("operation", ["checkout", "merge", "reset"])
def test_late_policy_refusal_preserves_saved_stash_and_head(repo, tmp_path, operation):
    root, git, raw = repo
    (root / "package-lock.json").write_bytes(b"saved local content\n")
    stash = update._stash_local_changes_if_needed([git], root)
    head = raw("rev-parse", "HEAD").stdout
    config = tmp_path / "late-inactive"
    config.write_text('[include]\npath = nested\n', encoding="utf-8")
    raw("config", "includeIf.gitdir:inactive.path", str(config))
    args = {"checkout": ["checkout", "-B", "other", "HEAD"],
            "merge": ["merge", "--ff-only", "HEAD"], "reset": ["reset", "--hard", "HEAD"]}[operation]
    with pytest.raises(compat.GitPolicyError):
        update._run_update_git([git, *args], cwd=root)
    assert raw("rev-parse", "HEAD").stdout == head
    assert raw("rev-parse", "refs/stash").stdout.strip() == stash
    assert "saved local content" in raw("show", stash + ":package-lock.json").stdout


def test_owned_fetch_remote_config_and_push_remain_operable(repo, tmp_path):
    root, git, raw = repo
    origin = tmp_path / "owned-origin.git"
    raw("clone", "--bare", str(root), str(origin))
    update._run_update_git([git, "remote", "add", "origin", str(origin)], cwd=root, check=True)
    assert update._get_origin_url([git], root) == str(origin)
    update._run_update_git([git, "fetch", "origin"], cwd=root, check=True)
    update._run_update_git([git, "push", "origin", "HEAD"], cwd=root, check=True)


def test_windows_version_descriptor_uses_selected_physical_git(repo):
    root, git, raw = repo
    result = update._run_update_git([git, "-c", "windows.appendAtomically=false", "--version"])
    assert result.returncode == 0 and result.stdout.startswith("git version ")
    assert not update._git_is_trampoline([git, "-c", "windows.appendAtomically=false"])


def test_git_candidate_nonzero_is_not_selected(tmp_path, monkeypatch):
    candidate = tmp_path / "owned-git.exe"
    candidate.write_bytes(b"fixture only; never executed")
    monkeypatch.setattr(update, "_portable_git_candidates", lambda: [candidate])
    monkeypatch.setattr(update, "_run_update_git", lambda *a, **kw:
                        subprocess.CompletedProcess(a[0], 128, "", "owned unavailable Git"))
    assert update._locate_real_git() is None


def test_optional_upstream_fetch_nonzero_still_skips(repo, tmp_path, capsys):
    root, git, raw = repo
    raw("remote", "add", "upstream", str(tmp_path / "missing-owned-origin.git"))
    assert update._sync_with_upstream_if_needed([git], root, assume_yes=True) is False
    assert "Failed to fetch upstream. Skipping upstream sync." in capsys.readouterr().out


def test_missing_display_directory_keeps_empty_suffix(tmp_path):
    assert update._branch_head_suffix(["git"], tmp_path / "absent-owned-directory") == ""


def test_ff_only_only_classifies_actual_divergence(repo, monkeypatch):
    root, git, raw = repo
    base = raw("rev-parse", "HEAD").stdout.strip()
    raw("checkout", "-b", "remote-owned")
    (root / "remote.txt").write_bytes(b"remote\n")
    raw("add", "remote.txt")
    raw("commit", "-m", "remote")
    remote = raw("rev-parse", "HEAD").stdout.strip()
    raw("checkout", "-B", "local-owned", base)
    (root / "local.txt").write_bytes(b"local\n")
    raw("add", "local.txt")
    raw("commit", "-m", "local")
    raw("update-ref", "refs/remotes/origin/main", remote)
    head = raw("rev-parse", "HEAD").stdout
    refused = update._run_update_ff_only([git], root, "main")
    assert refused.returncode != 0 and raw("rev-parse", "HEAD").stdout == head
    monkeypatch.setattr(update, "_run_update_git", lambda *a, **kw:
                        subprocess.CompletedProcess([git, "merge"], 128, "", "fatal: owned config read failure"))
    with pytest.raises(update._UpdateGitExecutionError):
        update._run_update_ff_only([git], root, "main")


def test_eol_late_probe_failure_withholds_pin_and_success(repo, monkeypatch, capsys):
    root, git, raw = repo
    raw("config", "core.autocrlf", "true")
    (root / "package-lock.json").unlink()
    raw("checkout", "--", "package-lock.json")
    assert b"\r\n" in (root / "package-lock.json").read_bytes()
    import time
    os.utime(root / "package-lock.json", (time.time() + 5, time.time() + 5))
    original = update._run_update_eol_git
    restored = False
    def fail_late(command, **kwargs):
        nonlocal restored
        if restored and "diff" in command:
            return subprocess.CompletedProcess(command, 128, "", "owned late probe failure")
        result = original(command, **kwargs)
        if "checkout" in command:
            restored = True
        return result
    monkeypatch.setattr(update, "_run_update_eol_git", fail_late)
    update._normalize_managed_eol([git], root)
    assert restored and raw("config", "--get", "core.autocrlf").stdout.strip() == "true"
    assert "Normalized" not in capsys.readouterr().out


def test_lockfile_cleanup_preserves_intentional_package_change(repo):
    root, git, raw = repo
    (root / "package.json").write_bytes(b"original package\n")
    raw("add", "package.json")
    raw("commit", "-m", "tracked package")
    (root / "package.json").write_bytes(b"intentional package\n")
    (root / "package-lock.json").write_bytes(b"intentional lock\n")
    update._discard_lockfile_churn([git], root)
    assert (root / "package-lock.json").read_bytes() == b"intentional lock\n"
