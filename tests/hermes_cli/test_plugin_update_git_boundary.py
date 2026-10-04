"""Plugin update failures must preserve local edits and their recovery stash."""
import shlex
import shutil
import subprocess
import sys

import pytest

from hermes_cli import plugins_cmd as pc
from hermes_cli._subprocess_compat import GitPolicyError


@pytest.fixture
def scripted_git(monkeypatch):
    calls = []
    state = {"stash": ""}
    failures = {}
    saved = "a" * 40

    def run(_git, _target, *args, **kwargs):
        calls.append(args)
        key = args[0]
        if key == "status":
            key = "initial_status" if len(calls) == 1 else "restore_status"
        elif key == "rev-parse":
            key = "pre_ref" if not state["stash"] else "post_ref"
        elif key == "stash":
            key = args[1]
        if key == "push":
            state["stash"] = saved
        code, out, err = failures.get(key, (0, "", ""))
        if key == "initial_status" and key not in failures:
            out = " M plugin.py\n"
        elif key in {"pre_ref", "post_ref"} and key not in failures:
            out = state["stash"]
            code = 0 if out else 1
        elif key == "pull" and key not in failures:
            out = "Updated\n"
        if key == "drop" and code == 0:
            state["stash"] = ""
        return subprocess.CompletedProcess(args, code, out, err)

    monkeypatch.setattr(pc, "_resolve_git_executable", lambda: "owned-git")
    monkeypatch.setattr(pc, "_run_plugin_git", run)
    return calls, state, failures, saved


@pytest.mark.parametrize("code", [1, 124, 127, 128])
def test_failed_initial_status_never_updates(tmp_path, scripted_git, code):
    calls, _, failures, _ = scripted_git
    failures["initial_status"] = (code, "", "status failed")
    ok, _ = pc._git_pull_plugin_dir(tmp_path)
    assert not ok
    assert calls == [("status", "--porcelain")]


@pytest.mark.parametrize("stage", ["pre_ref", "post_ref"])
def test_failed_stash_reference_never_pulls_or_resets(tmp_path, scripted_git, stage):
    calls, _, failures, _ = scripted_git
    failures[stage] = (128, "", "cannot read reference")
    ok, _ = pc._git_pull_plugin_dir(tmp_path)
    assert not ok
    assert not any(c[0] in {"pull", "reset"} for c in calls)
    assert not any(c[:2] == ("stash", "drop") for c in calls)


@pytest.mark.parametrize("pull_failed", [False, True])
@pytest.mark.parametrize("stage", ["apply", "diff", "restore_status", "drop"])
def test_failed_recovery_does_not_claim_success_or_drop_saved_edits(
    tmp_path, scripted_git, stage, pull_failed
):
    calls, state, failures, saved = scripted_git
    failures[stage] = (1, "", "recovery failed")
    if pull_failed:
        failures["pull"] = (1, "", "pull failed")
    ok, _ = pc._git_pull_plugin_dir(tmp_path)
    assert not ok
    assert state["stash"] == saved
    if stage != "drop":
        assert not any(c[:2] == ("stash", "drop") for c in calls)
    if stage in {"diff", "restore_status"}:
        assert not any(c[0] == "reset" for c in calls)


@pytest.mark.parametrize("push_failed", [False, True])
def test_failed_reset_preserves_stash_and_reports_failure(tmp_path, scripted_git, push_failed):
    calls, state, failures, saved = scripted_git
    failures["reset"] = (1, "", "reset failed")
    if push_failed:
        failures["push"] = (1, "", "saved but could not clean")
    else:
        failures["apply"] = (1, "", "conflict")
        failures["diff"] = (0, "plugin.py\n", "")
    ok, _ = pc._git_pull_plugin_dir(tmp_path)
    assert not ok
    assert state["stash"] == saved
    assert not any(c[:2] == ("stash", "drop") for c in calls)
    if push_failed:
        assert not any(c[0] == "pull" for c in calls)


def test_conflict_keeps_recoverable_stash_even_after_successful_reset(tmp_path, scripted_git):
    _, state, failures, saved = scripted_git
    failures["apply"] = (1, "", "conflict")
    failures["diff"] = (0, "plugin.py\n", "")
    ok, message = pc._git_pull_plugin_dir(tmp_path)
    assert not ok
    assert state["stash"] == saved
    assert "stash" in message


def test_successful_restore_applies_saved_commit_and_drops_only_verified_entry(tmp_path, scripted_git):
    calls, state, _, saved = scripted_git
    ok, _ = pc._git_pull_plugin_dir(tmp_path)
    assert ok
    assert ("stash", "apply", saved) in calls
    assert state["stash"] == ""


@pytest.mark.parametrize("pull_failed", [False, True])
def test_changed_top_stash_is_never_applied_or_dropped(tmp_path, scripted_git, monkeypatch, pull_failed):
    calls, state, failures, saved = scripted_git
    original = pc._run_plugin_git

    def change_top(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[2] == "pull":
            state["stash"] = "b" * 40
        return result

    monkeypatch.setattr(pc, "_run_plugin_git", change_top)
    if pull_failed:
        failures["pull"] = (1, "", "pull failed")
    ok, _ = pc._git_pull_plugin_dir(tmp_path)
    assert not ok
    assert ("stash", "apply", saved) in calls
    assert state["stash"] == "b" * 40
    assert not any(c[:2] == ("stash", "drop") for c in calls)


@pytest.mark.parametrize("operation", ["clean", "smudge", "textconv"])
def test_native_plugin_git_does_not_execute_repository_filter(tmp_path, operation):
    git = shutil.which("git")
    assert git, "Native Git is required for this boundary test"
    repo = tmp_path / "plugin"
    repo.mkdir()

    def setup(*args):
        return subprocess.run([git, *args], cwd=repo, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=15, check=True)

    setup("init", "-q")
    setup("config", "user.name", "fixture")
    setup("config", "user.email", "fixture@example.invalid")
    (repo / ".gitattributes").write_text("*.txt filter=evil diff=evil\n", encoding="utf-8")
    file = repo / "owned.txt"
    file.write_text("before\n", encoding="utf-8")
    setup("add", ".")
    setup("commit", "-qm", "fixture")
    marker = tmp_path / "filter-executed.txt"
    program = f"import pathlib,sys;pathlib.Path({str(marker)!r}).write_text('executed');sys.stdout.write(sys.stdin.read())"
    command = shlex.quote(sys.executable.replace("\\", "/")) + " -c " + shlex.quote(program)
    key = f"diff.evil.textconv" if operation == "textconv" else f"filter.evil.{operation}"
    setup("config", key, command)
    file.write_text("after\n", encoding="utf-8")
    args = {"clean": ("add", "--", "owned.txt"),
            "smudge": ("checkout", "--", "owned.txt"),
            "textconv": ("diff", "--no-ext-diff")}[operation]
    result = pc._run_plugin_git(git, repo, *args)
    assert result.returncode == 0, result.stderr
    assert not marker.exists()


def test_native_malformed_discovery_aborts_before_update(tmp_path, monkeypatch):
    git = shutil.which("git")
    assert git
    repo = tmp_path / "plugin"
    repo.mkdir()
    subprocess.run([git, "init", "-q"], cwd=repo, check=True,
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
    (repo / ".git" / "inactive-policy").write_text("[malformed\n", encoding="utf-8")
    with (repo / ".git" / "config").open("a", encoding="utf-8") as stream:
        stream.write('\n[includeIf "gitdir:never-active/"]\npath = inactive-policy\n')
    monkeypatch.setattr(pc, "_resolve_git_executable", lambda: git)
    ok, _ = pc._git_pull_plugin_dir(repo)
    assert not ok
    assert not (repo / ".git" / "FETCH_HEAD").exists()


@pytest.mark.parametrize("value", ["", "not-a-commit", "a" * 39, "a" * 41])
def test_invalid_successful_stash_ref_aborts_before_push(tmp_path, scripted_git, value):
    calls, _, failures, _ = scripted_git
    failures["pre_ref"] = (0, value, "")
    ok, _ = pc._git_pull_plugin_dir(tmp_path)
    assert not ok
    assert not any(c[0] in {"pull", "stash", "reset"} for c in calls)


@pytest.mark.parametrize("exception", [GitPolicyError("refused"), OSError("unavailable"), subprocess.TimeoutExpired("git", 60)])
def test_exception_during_recovery_preserves_stash(tmp_path, scripted_git, monkeypatch, exception):
    calls, state, _, saved = scripted_git
    original = pc._run_plugin_git

    def fail_apply(*args, **kwargs):
        if args[2:4] == ("stash", "apply"):
            raise exception
        return original(*args, **kwargs)

    monkeypatch.setattr(pc, "_run_plugin_git", fail_apply)
    ok, message = pc._git_pull_plugin_dir(tmp_path)
    assert not ok
    assert state["stash"] == saved
    assert "stash" in message
    assert not any(c[:2] == ("stash", "drop") for c in calls)


def test_saved_but_nonzero_push_can_recover_after_successful_reset(tmp_path, scripted_git):
    calls, state, failures, _ = scripted_git
    failures["push"] = (1, "", "could not remove tracked file")
    ok, _ = pc._git_pull_plugin_dir(tmp_path)
    assert ok
    assert ("reset", "--hard", "HEAD") in calls
    assert not state["stash"]
