"""Internal Git callers must not execute repository-selected filter commands."""
from __future__ import annotations

from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

from hermes_cli._subprocess_compat import noninteractive_git_env


def test_binary_probe_limit_is_per_stream_and_preserves_bytes(tmp_path):
    from hermes_cli._subprocess_compat import bounded_probe_run
    result = bounded_probe_run([sys.executable, '-I', '-c',
        "import sys;sys.stdout.buffer.write(b'x'*4096);sys.stderr.buffer.write(b'y'*4096)"],
        cwd=tmp_path, timeout=5, binary_output=True, max_output_bytes=4096)
    assert result is not None
    assert result.returncode == 0
    assert result.stdout == b'x' * 4096
    assert result.stderr == b'y' * 4096


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_binary_probe_limit_refuses_either_overflow(tmp_path, stream):
    from hermes_cli._subprocess_compat import bounded_probe_run
    result = bounded_probe_run([sys.executable, '-I', '-c',
        f"import sys;sys.{stream}.buffer.write(b'x'*4097)"],
        cwd=tmp_path, timeout=5, binary_output=True, max_output_bytes=4096)
    assert result is None


def test_binary_probe_limit_preserves_execution_deadline(tmp_path):
    from hermes_cli._subprocess_compat import bounded_probe_run
    # Ordinary finite delay verifies bounded execution without external resources.
    result = bounded_probe_run([sys.executable, '-I', '-c',
        "import time;time.sleep(10)"], cwd=tmp_path, timeout=.1,
        binary_output=True, max_output_bytes=4096)
    assert result is None


def test_binary_probe_limit_refuses_overflow_at_final_poll(tmp_path, monkeypatch):
    import os
    import threading
    import time
    from hermes_cli import _subprocess_compat as compat
    native_popen, native_read, native_thread = subprocess.Popen, os.read, threading.Thread
    polling = threading.Event()
    pipe_fds = set()
    readers = []

    def tracked_thread(*args, **kwargs):
        reader = native_thread(*args, **kwargs)
        readers.append(reader)
        return reader

    def synchronized_read(fd, count):
        if fd in pipe_fds:
            assert polling.wait(3), 'Fixture did not reach the final poll'
        return native_read(fd, count)

    class PollBoundary:
        def __init__(self, *args, **kwargs):
            self.child = native_popen(*args, **kwargs)
            pipe_fds.update((self.child.stdout.fileno(), self.child.stderr.fileno()))

        def __getattr__(self, name):
            return getattr(self.child, name)

        def poll(self):
            polling.set()
            expires = time.monotonic() + 3
            while self.child.poll() is None or any(reader.is_alive() for reader in readers):
                assert time.monotonic() < expires, 'Finite owned readers did not finish'
                time.sleep(.001)
            return self.child.poll()

    monkeypatch.setattr(compat.os, 'read', synchronized_read)
    monkeypatch.setattr(compat.threading, 'Thread', tracked_thread)
    monkeypatch.setattr(compat.subprocess, 'Popen', PollBoundary)
    result = compat.bounded_probe_run([sys.executable, '-I', '-c',
        "import sys;sys.stdout.buffer.write(b'x'*16384)"], cwd=tmp_path,
        timeout=5, binary_output=True, max_output_bytes=4096)
    assert result is None


@pytest.fixture
def owned_repo(tmp_path):
    git = shutil.which("git")
    assert git, "Native Git is required for this execution-boundary test"
    repo = tmp_path / "owned repo"
    repo.mkdir()
    env = noninteractive_git_env()
    env.update({"HOME": str(tmp_path), "USERPROFILE": str(tmp_path)})
    def setup(*args):
        return subprocess.run([git, "-C", str(repo), *args], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", timeout=10, check=True)
    setup("init", "--initial-branch=fixture")
    setup("config", "user.email", "fixture@example.invalid")
    setup("config", "user.name", "Owned fixture")
    (repo / ".gitattributes").write_text("*.txt filter=fixture\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("original fixture content\n", encoding="utf-8")
    setup("add", ".")
    setup("commit", "-m", "Owned fixture baseline")
    return repo, setup


def marker_command(tmp_path: Path, marker: Path) -> str:
    script = tmp_path / (marker.stem + " filter.py")
    script.write_text(
        "import pathlib,sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('OWNED_FILTER_EXECUTED', encoding='utf-8')\n"
        "sys.stdout.buffer.write(sys.stdin.buffer.read())\n",
        encoding="utf-8",
    )
    return " ".join(shlex.quote(value.replace("\\", "/"))
                    for value in (sys.executable, "-I", str(script)))


def process_filter_command(tmp_path: Path, marker: Path) -> str:
    script = tmp_path / "owned process filter.py"
    script.write_text(
        "import pathlib,sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('OWNED_PROCESS_FILTER_EXECUTED', encoding='utf-8')\n"
        "reader,writer=sys.stdin.buffer,sys.stdout.buffer\n"
        "def group():\n"
        "    packets=[]\n"
        "    while True:\n"
        "        prefix=reader.read(4)\n"
        "        if not prefix: return None\n"
        "        length=int(prefix,16)\n"
        "        if length==0: return packets\n"
        "        packets.append(reader.read(length-4))\n"
        "def send(packets):\n"
        "    for packet in packets:\n"
        "        writer.write(f'{len(packet)+4:04x}'.encode()+packet)\n"
        "    writer.write(b'0000'); writer.flush()\n"
        "assert group()==[b'git-filter-client\\n',b'version=2\\n']\n"
        "send([b'git-filter-server\\n',b'version=2\\n'])\n"
        "assert group() is not None\n"
        "send([b'capability=clean\\n',b'capability=smudge\\n'])\n"
        "while group() is not None:\n"
        "    content=group()\n"
        "    if content is None: break\n"
        "    send([b'status=success\\n']); send(content); send([])\n",
        encoding="utf-8",
    )
    return " ".join(shlex.quote(value.replace("\\", "/"))
                    for value in (sys.executable, "-I", str(script)))


def internal_git(surface: str, repo: Path, args: list[str]):
    if surface == "delegation":
        from tools.subagent_worktree import _run_git
        result = _run_git(args, cwd=str(repo), timeout=10)
        return result.returncode, result.stdout, result.stderr
    if surface == "reclaim":
        from hermes_cli.worktree_gc import _git
        result = _git(args, cwd=str(repo), timeout=10)
        return result.returncode, result.stdout, result.stderr
    from hermes_cli.web_git import _git
    return _git(str(repo), args, timeout=10)


@pytest.mark.parametrize("surface", ["delegation", "reclaim", "web"])
def test_internal_diff_neutralizes_repository_clean_filter(surface, owned_repo, tmp_path):
    repo, setup = owned_repo
    marker = tmp_path / "clean-marker"
    setup("config", "filter.fixture.clean", marker_command(tmp_path, marker))
    setup("config", "filter.fixture.required", "true")
    (repo / "tracked.txt").write_text("modified fixture with a different size\n", encoding="utf-8")
    code, stdout, stderr = internal_git(surface, repo, ["diff", "--numstat", "--no-ext-diff", "--no-textconv"])
    assert code == 0, stderr
    assert "tracked.txt" in stdout
    assert not marker.exists(), "Internal diff executed a repository-owned clean command"


@pytest.mark.parametrize("surface", ["delegation", "reclaim", "web"])
def test_internal_worktree_neutralizes_repository_smudge_filter(surface, owned_repo, tmp_path):
    repo, setup = owned_repo
    marker = tmp_path / "smudge-marker"
    setup("config", "filter.fixture.smudge", marker_command(tmp_path, marker))
    setup("config", "filter.fixture.required", "true")
    destination = tmp_path / "owned worktree"
    code, _, stderr = internal_git(surface, repo, ["worktree", "add", "--detach", str(destination), "HEAD"])
    assert code == 0, stderr
    assert (destination / "tracked.txt").read_text(encoding="utf-8") == "original fixture content\n"
    assert not marker.exists(), "Internal checkout executed a repository-owned smudge command"


@pytest.mark.parametrize("surface", ["delegation", "reclaim", "web"])
def test_internal_diff_neutralizes_attribute_textconv(surface, owned_repo, tmp_path):
    repo, setup = owned_repo
    marker = tmp_path / "textconv-marker"
    setup("config", "diff.fixture.textconv", marker_command(tmp_path, marker))
    (repo / ".gitattributes").write_text("*.txt diff=fixture\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("modified content for native diff\n", encoding="utf-8")
    code, stdout, stderr = internal_git(surface, repo, ["diff"])
    assert code == 0, stderr
    assert not marker.exists(), "Internal diff executed an attribute-selected text converter"
    assert "modified content for native diff" in stdout


@pytest.mark.parametrize("surface", ["delegation", "reclaim", "web"])
def test_internal_worktree_neutralizes_packet_process_filter(surface, owned_repo, tmp_path):
    repo, setup = owned_repo
    marker = tmp_path / "process-marker"
    setup("config", "filter.fixture.process", process_filter_command(tmp_path, marker))
    setup("config", "filter.fixture.required", "true")
    destination = tmp_path / "process worktree"
    code, _, stderr = internal_git(surface, repo, ["worktree", "add", "--detach", str(destination), "HEAD"])
    assert not marker.exists(), "Internal checkout started a repository packet-process filter"
    assert code == 0, stderr
    assert (destination / "tracked.txt").read_text(encoding="utf-8") == "original fixture content\n"


def test_owned_packet_filter_fixture_completes_real_git_protocol(owned_repo, tmp_path):
    repo, setup = owned_repo
    marker = tmp_path / "positive-process-marker"
    setup("config", "filter.fixture.process", process_filter_command(tmp_path, marker))
    setup("config", "filter.fixture.required", "true")
    destination = tmp_path / "positive protocol worktree"
    setup("worktree", "add", "--detach", str(destination), "HEAD")
    assert marker.read_text(encoding="utf-8") == "OWNED_PROCESS_FILTER_EXECUTED"
    assert (destination / "tracked.txt").read_text(encoding="utf-8") == "original fixture content\n"


@pytest.mark.parametrize("surface", ["delegation", "reclaim", "web"])
def test_internal_worktree_preserves_filter_subsection_case(surface, owned_repo, tmp_path):
    repo, setup = owned_repo
    (repo / "lower.txt").write_text("lower-case driver fixture\n", encoding="utf-8")
    (repo / ".gitattributes").write_text("tracked.txt filter=Evil\nlower.txt filter=evil\n", encoding="utf-8")
    setup("add", ".")
    setup("commit", "-m", "Owned case-sensitive driver fixture")
    markers = [tmp_path / "upper-driver-marker", tmp_path / "lower-driver-marker"]
    for name, marker in zip(("Evil", "evil"), markers):
        setup("config", f"filter.{name}.smudge", marker_command(tmp_path, marker))
        setup("config", f"filter.{name}.required", "true")
    destination = tmp_path / "case worktree"
    code, _, stderr = internal_git(surface, repo, ["worktree", "add", "--detach", str(destination), "HEAD"])
    assert not any(marker.exists() for marker in markers), "A distinct driver case escaped overrides"
    assert code == 0, stderr
    assert (destination / "lower.txt").read_text(encoding="utf-8") == "lower-case driver fixture\n"


@pytest.mark.parametrize("surface", ["delegation", "reclaim", "web"])
@pytest.mark.parametrize("include_kind", ["filter", "nested", "missing", "directory"])
def test_inactive_include_is_checked_before_branch_checkout(surface, include_kind, owned_repo, tmp_path):
    repo, setup = owned_repo
    marker = tmp_path / "inactive-include-marker"
    included = repo / ".git/inactive.conf"
    if include_kind == "directory":
        included.mkdir()
    elif include_kind != "missing":
        target = included
        if include_kind == "nested":
            target = included.with_name("nested.conf")
            setup("config", "--file", str(included), "include.path", "nested.conf")
        setup("config", "--file", str(target), "filter.fixture.smudge", marker_command(tmp_path, marker))
        setup("config", "--file", str(target), "filter.fixture.required", "true")
    setup("config", "includeIf.onbranch:owned-target.path", "inactive.conf")
    destination = tmp_path / "conditional worktree"
    code, _, stderr = internal_git(surface, repo, ["worktree", "add", "-b", "owned-target", str(destination), "HEAD"])
    assert not marker.exists(), "A future branch activated an undiscovered include command"
    if include_kind in ("nested", "directory"):
        assert code != 0, "Ambiguous include authority did not refuse"
        assert not destination.exists(), "Refusal happened after checkout writes"
    else:
        assert code == 0, stderr
        assert (destination / "tracked.txt").read_text(encoding="utf-8") == "original fixture content\n"


@pytest.mark.parametrize("surface", ["delegation", "reclaim", "web"])
def test_policy_discovery_failure_refuses_actual_git(surface, owned_repo, monkeypatch):
    from hermes_cli import _subprocess_compat
    repo, _ = owned_repo
    real_probe = _subprocess_compat.bounded_probe_run
    executed = []
    def refuse_discovery(argv, **kwargs):
        if "config" in argv and "--get-regexp" in argv:
            return None
        executed.append(argv)
        return real_probe(argv, **kwargs)
    monkeypatch.setattr(_subprocess_compat, "bounded_probe_run", refuse_discovery)
    code, stdout, _ = internal_git(surface, repo, ["status", "--porcelain"])
    assert code != 0, "Discovery refusal fell through to a real Git operation"
    assert not stdout
    assert not executed, "Discovery failure allowed an actual Git operation"


@pytest.mark.parametrize("surface", ["delegation", "reclaim", "web"])
def test_valid_internal_git_retains_content_and_status(surface, owned_repo):
    repo, _ = owned_repo
    code, stdout, stderr = internal_git(surface, repo, ["show", "HEAD:tracked.txt"])
    assert code == 0, stderr
    assert stdout == "original fixture content\n"
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == stdout


def context_probe(surface: str, repo: Path, *args: str) -> str:
    if surface == "coding":
        from agent.coding_context import _git
        return _git(repo, *args)
    from tui_gateway.git_probe import run_git
    return run_git(str(repo), *args)


@pytest.mark.parametrize("surface", ["coding", "gateway"])
@pytest.mark.parametrize("sink", ["clean", "textconv"])
def test_context_probe_neutralizes_repository_programs(surface, sink, owned_repo, tmp_path):
    repo, setup = owned_repo
    marker = tmp_path / (sink + "-context-marker")
    command = marker_command(tmp_path, marker)
    if sink == "clean":
        setup("config", "filter.fixture.clean", command)
    else:
        setup("config", "diff.fixture.textconv", command)
        (repo / ".gitattributes").write_text("*.txt diff=fixture\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("modified native context fixture\n", encoding="utf-8")
    result = context_probe(surface, repo, "diff")
    assert not marker.exists(), "Context probe executed a repository-selected program"
    assert "modified native context fixture" in result


@pytest.mark.parametrize("surface", ["coding", "gateway"])
def test_context_probe_does_not_fall_back_after_discovery_failure(surface, owned_repo, monkeypatch):
    from hermes_cli import _subprocess_compat
    repo, _ = owned_repo
    original = _subprocess_compat.bounded_probe_run
    def refuse_discovery(argv, **kwargs):
        return None if "config" in argv else original(argv, **kwargs)
    monkeypatch.setattr(_subprocess_compat, "bounded_probe_run", refuse_discovery)
    assert context_probe(surface, repo, "rev-parse", "HEAD") == ""


@pytest.mark.parametrize("surface", ["delegation", "reclaim", "web"])
def test_inactive_home_include_uses_git_child_home(surface, owned_repo, tmp_path, monkeypatch):
    repo, setup = owned_repo
    home, profile = tmp_path / "git home", tmp_path / "different userprofile"
    home.mkdir()
    profile.mkdir()
    marker = tmp_path / "git-home-include-marker"
    included = home / "owned.inc"
    setup("config", "--file", str(included), "filter.fixture.smudge", marker_command(tmp_path, marker))
    setup("config", "includeIf.onbranch:owned-target.path", "~/owned.inc")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(profile))
    destination = tmp_path / "child home worktree"
    code, _, stderr = internal_git(surface, repo, ["worktree", "add", "-b", "owned-target", str(destination), "HEAD"])
    assert not marker.exists(), "Discovery expanded include against a different home from Git"
    assert code == 0, stderr


@pytest.mark.parametrize("surface", ["delegation", "reclaim", "web"])
@pytest.mark.parametrize("switch", ["other-repo", "inline-filter"])
def test_argv_cannot_change_discovered_execution_authority(surface, switch, owned_repo, tmp_path):
    repo, setup = owned_repo
    marker = tmp_path / "argv-authority-marker"
    command = marker_command(tmp_path, marker)
    if switch == "other-repo":
        other = tmp_path / "other owned repo"
        setup("clone", "--no-local", str(repo), str(other))
        setup("-C", str(other), "config", "filter.fixture.clean", command)
        (other / "tracked.txt").write_text("other repo content changed\n", encoding="utf-8")
        args = ["-C", str(other), "diff"]
    else:
        (repo / "tracked.txt").write_text("inline filter content changed\n", encoding="utf-8")
        args = ["-c", "filter.fixture.clean=" + command, "diff"]
    code, _, _ = internal_git(surface, repo, args)
    assert not marker.exists(), "Git argv escaped the repository/configuration that was discovered"
    assert code != 0, "Unsupported authority change must be refused"


@pytest.mark.parametrize("option", ["--textconv", "--ext-diff", "--textcon", "--ext-di"])
def test_web_review_base_cannot_reenable_repository_driver(option, owned_repo, tmp_path):
    from hermes_cli.web_git import review_diff
    repo, setup = owned_repo
    marker = tmp_path / "public-base-marker"
    variable = "textconv" if option.startswith("--textcon") else "command"
    setup("config", f"diff.fixture.{variable}", marker_command(tmp_path, marker))
    (repo / ".gitattributes").write_text("*.txt diff=fixture\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("public review fixture changed\n", encoding="utf-8")
    result = review_diff(str(repo), "tracked.txt", "lastTurn", option, False)
    assert not marker.exists(), "Public base option reenabled an attribute program"
    assert result == "", "An invalid option-shaped base must not become an implicit diff"


@pytest.mark.parametrize("surface", ["delegation", "reclaim", "web"])
def test_explicit_commit_identity_configuration_remains_supported(surface, owned_repo):
    repo, _ = owned_repo
    code, stdout, stderr = internal_git(surface, repo, ["-c", "user.name=Owned Operator",
        "-c", "user.email=owned@example.invalid", "show", "HEAD:tracked.txt"])
    assert code == 0, stderr
    assert stdout == "original fixture content\n"


@pytest.mark.parametrize("surface", ["delegation", "reclaim", "web"])
def test_ambient_config_file_cannot_hide_repository_filter_inventory(surface, owned_repo, tmp_path, monkeypatch):
    repo, setup = owned_repo
    marker = tmp_path / "ambient-config-marker"
    setup("config", "filter.fixture.clean", marker_command(tmp_path, marker))
    (repo / "tracked.txt").write_text("ambient configuration fixture changed\n", encoding="utf-8")
    unrelated = tmp_path / "empty ambient config"
    unrelated.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG", str(unrelated))
    code, stdout, stderr = internal_git(surface, repo, ["diff"])
    assert not marker.exists(), "Ambient config hid the actual repository's filter inventory"
    assert code == 0, stderr
    assert "ambient configuration fixture changed" in stdout


def test_cli_parallel_checkout_configuration_remains_supported(owned_repo, tmp_path):
    from hermes_cli._subprocess_compat import run_internal_git
    repo, _ = owned_repo
    target = tmp_path / "parallel checkout"
    result = run_internal_git(["-c", "checkout.workers=8", "-c",
        "checkout.thresholdForParallelism=100", "worktree", "add", "--detach", str(target)],
        repo, timeout=10)
    assert result.returncode == 0, result.stderr
    assert (target / "tracked.txt").read_text(encoding="utf-8") == "original fixture content\n"


def test_inactive_include_path_expansion_has_a_probe_budget(owned_repo, tmp_path, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    for index in range(20):
        setup("config", f"includeIf.onbranch:inactive-{index}.path", "~/missing fixture.inc")
    real_probe = compat.bounded_probe_run
    expansions = []
    def counted_probe(argv, **kwargs):
        if "--path" in argv:
            expansions.append(argv)
        return real_probe(argv, **kwargs)
    monkeypatch.setattr(compat, "bounded_probe_run", counted_probe)
    env = compat.noninteractive_repo_git_env(repo)
    assert len(expansions) <= 16, "Inactive includes bypassed the discovery subprocess budget"
    assert env is None, "Over-budget configuration must refuse execution"


def test_cli_worktree_setup_neutralizes_filter(owned_repo, tmp_path):
    import cli
    repo, setup = owned_repo
    marker = tmp_path / "cli-smudge-marker"
    setup("config", "filter.fixture.smudge", marker_command(tmp_path, marker))
    info = cli._setup_worktree(str(repo), sync_base=False, name="owned-fixture")
    assert info is not None
    assert not marker.exists(), "CLI setup bypassed repository filter policy"
    assert (Path(info["path"]) / "tracked.txt").read_text(encoding="utf-8") == "original fixture content\n"


def test_cli_setup_discovery_refusal_precedes_any_repository_write(owned_repo, monkeypatch):
    import cli
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    before = setup("worktree", "list", "--porcelain").stdout
    monkeypatch.setattr(compat, "noninteractive_repo_git_env", lambda *a, **kw: None)
    info = cli._setup_worktree(str(repo), sync_base=False, name="refused-fixture")
    assert info is None, "CLI created a worktree after discovery refusal"
    assert not (repo / ".worktrees").exists()
    assert not (repo / ".gitignore").exists()
    assert setup("worktree", "list", "--porcelain").stdout == before


def test_cli_failure_cleanup_refusal_preserves_owned_worktree(owned_repo, tmp_path, monkeypatch):
    import cli
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    target = tmp_path / "owned partial worktree"
    branch = "hermes/owned-cleanup-fixture"
    setup("worktree", "add", str(target), "-b", branch)
    setup("worktree", "lock", str(target), "--reason", "Owned incomplete fixture")
    content = (target / "tracked.txt").read_bytes()
    before = setup("worktree", "list", "--porcelain").stdout
    monkeypatch.setattr(compat, "noninteractive_repo_git_env", lambda *a, **kw: None)
    cli._cleanup_failed_worktree_add(str(repo), target, branch)
    assert target.exists(), "Discovery refusal fell through to destructive cleanup"
    assert (target / "tracked.txt").read_bytes() == content
    assert setup("worktree", "list", "--porcelain").stdout == before
    assert setup("rev-parse", "--verify", branch).returncode == 0


def test_cli_worktree_base_discovery_refusal_cannot_become_local_fallback(owned_repo, monkeypatch):
    import cli
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    monkeypatch.setattr(compat, "noninteractive_repo_git_env", lambda *a, **kw: None)
    with pytest.raises(RuntimeError, match="git filter discovery failed"):
        cli._resolve_worktree_base(str(repo))


def test_cli_dirty_probe_neutralizes_clean_filter(owned_repo, tmp_path):
    import cli
    repo, setup = owned_repo
    marker = tmp_path / "cli-dirty-marker"
    setup("config", "filter.fixture.clean", marker_command(tmp_path, marker))
    (repo / "tracked.txt").write_text("dirty CLI owned fixture\n", encoding="utf-8")
    assert cli._worktree_is_dirty(str(repo))
    assert not marker.exists(), "CLI dirty probe executed repository clean command"


def test_kanban_worktree_setup_neutralizes_filter(owned_repo, tmp_path):
    from hermes_cli.kanban_db import _ensure_git_worktree
    repo, setup = owned_repo
    marker = tmp_path / "kanban-smudge-marker"
    setup("config", "filter.fixture.smudge", marker_command(tmp_path, marker))
    target = tmp_path / "owned kanban workspace"
    _ensure_git_worktree(repo, target, "wt/owned-fixture")
    assert not marker.exists(), "Kanban worktree bypassed repository filter policy"
    assert (target / "tracked.txt").read_text(encoding="utf-8") == "original fixture content\n"


def test_kanban_discovery_refusal_precedes_directory_creation(owned_repo, tmp_path, monkeypatch):
    from hermes_cli.kanban_db import _ensure_git_worktree
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    target = tmp_path / "never created kanban parent" / "workspace"
    before = setup("worktree", "list", "--porcelain").stdout
    monkeypatch.setattr(compat, "noninteractive_repo_git_env", lambda *a, **kw: None)
    with pytest.raises(RuntimeError, match="git filter discovery failed"):
        _ensure_git_worktree(repo, target, "wt/refused-fixture")
    assert not target.parent.exists()
    assert setup("worktree", "list", "--porcelain").stdout == before


def test_banner_git_probe_neutralizes_filter(owned_repo, tmp_path):
    from hermes_cli.banner import _git_run
    repo, setup = owned_repo
    marker = tmp_path / "banner-clean-marker"
    setup("config", "filter.fixture.clean", marker_command(tmp_path, marker))
    (repo / "tracked.txt").write_text("banner owned fixture changed\n", encoding="utf-8")
    result = _git_run(["diff", "--numstat"], cwd=repo)
    assert result is not None and result.returncode == 0
    assert not marker.exists(), "Banner plumbing bypassed repository filter policy"


@pytest.mark.parametrize("surface", ["web", "reclaim"])
def test_gh_wrapper_discovery_refusal_never_invokes_gh(surface, owned_repo, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    calls = []
    def capture(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "{}", "")
    monkeypatch.setattr(compat, "noninteractive_repo_git_env", lambda *a, **kw: None)
    original_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, *a, **kw: sys.executable if name == "gh" else original_which(name, *a, **kw))
    monkeypatch.setattr(subprocess, "run", capture)
    if surface == "web":
        from hermes_cli.web_git import _gh
        ok, _ = _gh(str(repo), ["pr", "view"])
        assert not ok
    else:
        from hermes_cli.worktree_gc import _gh
        result = _gh(["pr", "view"], str(repo))
        assert result.returncode != 0
    assert not calls, "Repository policy refusal fell through to gh"


def test_cli_pack_maintenance_refusal_never_invokes_repack(owned_repo, monkeypatch):
    import cli
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    calls = []
    monkeypatch.setattr(cli, "_PACK_SPRAWL_THRESHOLD", 0)
    monkeypatch.setattr(compat, "noninteractive_repo_git_env", lambda *a, **kw: None)
    def capture(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", capture)
    cli._maintain_pack_health(str(repo))
    assert not calls, "Pack maintenance ran a raw Git command after discovery refusal"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows environment key aliases")
def test_windows_ambient_config_case_alias_cannot_hide_filter_inventory(owned_repo, tmp_path):
    import os
    from hermes_cli._subprocess_compat import run_internal_git
    repo, setup = owned_repo
    marker = tmp_path / "case-ambient-config-marker"
    setup("config", "filter.fixture.clean", marker_command(tmp_path, marker))
    (repo / "tracked.txt").write_text("case ambient fixture changed\n", encoding="utf-8")
    unrelated = tmp_path / "case empty config"
    unrelated.write_text("", encoding="utf-8")
    base = dict(os.environ)
    base["git_config"] = str(unrelated)
    result = run_internal_git(["diff", "--numstat"], repo, timeout=10, base=base)
    assert not marker.exists(), "Windows case alias hid actual repository filter configuration"
    assert result.returncode == 0, result.stderr


def test_owned_gh_child_retains_policy_when_it_delegates_git(owned_repo, tmp_path):
    from hermes_cli._subprocess_compat import run_internal_gh
    repo, setup = owned_repo
    marker = tmp_path / "owned-gh-filter-marker"
    setup("config", "filter.fixture.clean", marker_command(tmp_path, marker))
    (repo / "tracked.txt").write_text("owned gh child fixture changed\n", encoding="utf-8")
    script = tmp_path / "owned gh fixture.py"
    script.write_text(
        "import os,shutil,subprocess,sys\n"
        "assert os.environ['GH_PROMPT_DISABLED']=='1'\n"
        "assert os.environ['GIT_TERMINAL_PROMPT']=='0'\n"
        "assert sys.stdin.buffer.read()==b''\n"
        "p=subprocess.run([shutil.which('git'),'diff','--numstat'],stdin=subprocess.DEVNULL,"
        "capture_output=True,text=True,encoding='utf-8',timeout=10)\n"
        "sys.stdout.write(p.stdout);sys.stderr.write(p.stderr);sys.exit(p.returncode)\n",
        encoding="utf-8",
    )
    result = run_internal_gh(["-I", str(script)], repo, timeout=15, gh_bin=sys.executable)
    assert result.returncode == 0, result.stderr
    assert "tracked.txt" in result.stdout
    assert not marker.exists(), "Owned gh child delegated Git with unsafe environment"


def test_cli_cleanup_refusal_stops_head_retry(owned_repo, monkeypatch):
    import cli
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    original_policy = compat.noninteractive_repo_git_env
    attempts = []
    count = 0
    def policy(*args, **kwargs):
        nonlocal count
        count += 1
        return None if count == 3 else original_policy(*args, **kwargs)
    real_probe = compat.bounded_probe_run
    def probe(argv, **kwargs):
        if "worktree" in argv and "add" in argv:
            attempts.append(argv)
        return real_probe(argv, **kwargs)
    monkeypatch.setattr(compat, "noninteractive_repo_git_env", policy)
    monkeypatch.setattr(compat, "bounded_probe_run", probe)
    monkeypatch.setattr(cli, "_resolve_worktree_base", lambda *a, **kw: ("origin/missing-fixture", "Owned unavailable base"))
    info = cli._setup_worktree(str(repo), name="cleanup-refusal")
    assert info is None, "Cleanup refusal was swallowed before a HEAD retry"
    assert len(attempts) == 1
    assert setup("branch", "--list", "hermes/cleanup-refusal").stdout.strip() == ""


def test_cli_orphan_branch_deletion_rechecks_policy(owned_repo, monkeypatch):
    import cli
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    branch = "hermes/hermes-owned-orphan"
    setup("branch", branch)
    original_policy = compat.noninteractive_repo_git_env
    count = 0
    def policy(*args, **kwargs):
        nonlocal count
        count += 1
        return None if count >= 4 else original_policy(*args, **kwargs)
    monkeypatch.setattr(compat, "noninteractive_repo_git_env", policy)
    cli._prune_orphaned_branches(str(repo))
    assert setup("branch", "--list", branch).stdout.strip(), "Orphan deletion bypassed a new policy refusal"


def test_kanban_branch_probe_refusal_precedes_directory_write(owned_repo, tmp_path, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    from hermes_cli.kanban_db import _ensure_git_worktree
    repo, _ = owned_repo
    original_policy = compat.noninteractive_repo_git_env
    count = 0
    def policy(*args, **kwargs):
        nonlocal count
        count += 1
        return None if count == 2 else original_policy(*args, **kwargs)
    monkeypatch.setattr(compat, "noninteractive_repo_git_env", policy)
    target = tmp_path / "refused branch parent" / "workspace"
    with pytest.raises(RuntimeError, match="git filter discovery failed"):
        _ensure_git_worktree(repo, target, "wt/refused-branch")
    assert not target.parent.exists(), "Kanban wrote a directory before branch authority was established"


def test_banner_fetch_refusal_has_no_raw_git_fallback(owned_repo, monkeypatch):
    from hermes_cli import banner
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    setup("remote", "add", "origin", str(repo))
    setup("update-ref", "refs/remotes/origin/main", "HEAD")
    original_git_run = banner._git_run
    original_run = subprocess.run
    raw_calls = []
    def capture(argv, **kwargs):
        if Path(argv[0]).name.lower() in {"git", "git.exe"}:
            raw_calls.append(argv)
        return original_run(argv, **kwargs)
    def refuse_fetch(args, **kwargs):
        if args and args[0] == "fetch":
            with monkeypatch.context() as patch:
                patch.setattr(compat, "noninteractive_repo_git_env", lambda *a, **kw: None)
                return original_git_run(args, **kwargs)
        return original_git_run(args, **kwargs)
    monkeypatch.setattr(subprocess, "run", capture)
    monkeypatch.setattr(banner, "_git_run", refuse_fetch)
    assert banner._check_via_local_git(repo) is None
    assert not raw_calls, "Banner discovery refusal reached an unprotected Git fallback"


@pytest.mark.parametrize("operation", ["short_hash", "release_tag"])
def test_banner_unavailable_git_returns_none(tmp_path, monkeypatch, operation):
    from hermes_cli import banner
    monkeypatch.setattr(banner, "_git_run", lambda *a, **kw: None)
    monkeypatch.setattr(banner, "_latest_release_cache", None)
    monkeypatch.setattr(banner, "_resolve_repo_dir", lambda: tmp_path)
    result = banner._git_short_hash(tmp_path, "HEAD") if operation == "short_hash" else banner.get_latest_release_tag()
    assert result is None


@pytest.mark.parametrize("surface", ["goal", "context"])
def test_remaining_internal_readers_neutralize_filter(surface, owned_repo, tmp_path):
    repo, setup = owned_repo
    marker = tmp_path / (surface + " reader marker")
    setup("config", "filter.fixture.clean", marker_command(tmp_path, marker))
    (repo / "tracked.txt").write_text("Changed owned reader content\n", encoding="utf-8")
    if surface == "goal":
        from hermes_cli.goals import workspace_fingerprint
        assert workspace_fingerprint(str(repo))
    else:
        from types import SimpleNamespace
        from agent.context_references import _expand_git_reference
        error, content = _expand_git_reference(SimpleNamespace(raw="@diff"), repo, ["diff"], "owned diff")
        assert error is None and "Changed owned reader content" in content
    assert not marker.exists(), "Internal reader executed an attribute-selected clean filter"


@pytest.mark.parametrize("surface", ["goal", "context", "dashboard", "ancestry"])
def test_remaining_internal_readers_stop_on_policy_refusal(surface, owned_repo, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    monkeypatch.setattr(compat, "noninteractive_repo_git_env", lambda *a, **kw: None)
    if surface == "goal":
        from hermes_cli.goals import workspace_fingerprint
        assert workspace_fingerprint(str(repo)) == ""
    elif surface == "context":
        from types import SimpleNamespace
        from agent.context_references import _expand_git_reference
        error, content = _expand_git_reference(SimpleNamespace(raw="@diff"), repo, ["diff"], "owned diff")
        assert error and "git filter discovery failed" in error and content is None
    elif surface == "dashboard":
        from hermes_cli.dashboard_managed_files import _fs_git_branch
        assert _fs_git_branch(str(repo)) == ""
    else:
        from hermes_cli.gitlock import is_ancestor_of_head
        assert not is_ancestor_of_head(repo, "HEAD")


def test_cli_worktree_list_stops_on_discovery_refusal(owned_repo, monkeypatch, capsys):
    import cli
    from hermes_cli import _subprocess_compat as compat
    from hermes_cli.cli_commands_mixin import CLICommandsMixin
    repo, _ = owned_repo
    monkeypatch.setattr(cli, "_git_repo_root", lambda: str(repo))
    monkeypatch.setattr(compat, "noninteractive_repo_git_env", lambda *a, **kw: None)
    CLICommandsMixin()._handle_worktree_command("/worktree list")
    output = capsys.readouterr().out
    assert "Could not list worktrees" in output
    assert str(repo) not in output


def test_working_diff_neutralizes_filter_and_preserves_unicode_paths(owned_repo, tmp_path):
    from tools.working_diff import collect_working_diff
    repo, setup = owned_repo
    marker = tmp_path / "working diff filter marker"
    setup("config", "filter.fixture.clean", marker_command(tmp_path, marker))
    (repo / "tracked.txt").write_text("Changed owned working diff\n", encoding="utf-8")
    (repo / "日本語の新規.txt").write_text("Owned Unicode addition\n", encoding="utf-8")
    result = collect_working_diff(str(repo))
    assert result["success"] and "Changed owned working diff" in result["diff"]
    assert "日本語の新規.txt" in result["diff"]
    assert not marker.exists(), "Shared CLI/gateway diff executed a repository clean filter"


def test_working_diff_late_policy_refusal_does_not_report_empty_success(owned_repo, monkeypatch):
    from tools.working_diff import collect_working_diff
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    original = compat.noninteractive_repo_git_env
    count = 0
    def refuse_later(*args, **kwargs):
        nonlocal count
        count += 1
        return None if count >= 2 else original(*args, **kwargs)
    monkeypatch.setattr(compat, "noninteractive_repo_git_env", refuse_later)
    result = collect_working_diff(str(repo))
    assert not result["success"] and "git filter discovery failed" in result["error"]


def test_working_diff_failed_diff_does_not_report_empty_success(owned_repo, monkeypatch):
    from tools.working_diff import collect_working_diff
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    original = compat.bounded_probe_run
    def fail_diff(argv, **kwargs):
        if "diff" in argv:
            return subprocess.CompletedProcess(argv, 124, "", "git failed or timed out")
        return original(argv, **kwargs)
    monkeypatch.setattr(compat, "bounded_probe_run", fail_diff)
    result = collect_working_diff(str(repo))
    assert not result["success"] and not result.get("empty")


@pytest.mark.parametrize("repo_value", [None, "false"])
def test_owned_system_eol_preserves_clean_and_modified_diff(owned_repo, tmp_path, monkeypatch, repo_value):
    from tools.working_diff import collect_working_diff
    repo, setup = owned_repo
    config = tmp_path / "owned Git system config"
    config.write_text("[core]\n    autocrlf=true\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "0")
    if repo_value is not None:
        setup("config", "core.autocrlf", repo_value)
    # Record LF bytes independently, then provide the legitimate Windows CRLF
    # checkout only when the effective EOL setting requests that conversion.
    setup("config", "core.autocrlf", "false")
    (repo / "tracked.txt").write_bytes(b"Owned EOL baseline\n")
    setup("add", "tracked.txt")
    setup("commit", "-m", "Owned EOL baseline")
    if repo_value is None:
        setup("config", "--unset", "core.autocrlf")
        (repo / "tracked.txt").write_bytes(b"Owned EOL baseline\r\n")
    clean = collect_working_diff(str(repo))
    assert clean["success"] and clean.get("empty"), "Safe system EOL inheritance changed a clean checkout"
    (repo / "tracked.txt").write_bytes(b"Owned EOL modification\r\n" if repo_value is None else b"Owned EOL modification\n")
    changed = collect_working_diff(str(repo))
    assert changed["success"] and "Owned EOL modification" in changed["diff"]


@pytest.mark.parametrize("command", ["ls-files", "no-index"])
def test_working_diff_untracked_probe_failure_is_not_success(command, owned_repo, monkeypatch):
    from tools.working_diff import collect_working_diff
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    (repo / "owned new file.txt").write_text("Owned new content\n", encoding="utf-8")
    original = compat.bounded_probe_run
    def fail_selected(argv, **kwargs):
        token = "--no-index" if command == "no-index" else command
        if token in argv:
            return subprocess.CompletedProcess(argv, 127, "", "Owned failed Git invocation")
        return original(argv, **kwargs)
    monkeypatch.setattr(compat, "bounded_probe_run", fail_selected)
    result = collect_working_diff(str(repo))
    assert not result["success"] and not result.get("empty")


@pytest.mark.parametrize("setting,value", [("autocrlf", "invalid"), ("eol", "invalid")])
def test_invalid_owned_eol_refuses_actual_git(setting, value, owned_repo, tmp_path, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    config = tmp_path / "owned invalid global config"
    config.write_text(f"[core]\n    {setting}={value}\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    executed = []
    probe = compat.bounded_probe_run
    def capture(argv, **kwargs):
        if "status" in argv:
            executed.append(argv)
        return probe(argv, **kwargs)
    monkeypatch.setattr(compat, "bounded_probe_run", capture)
    with pytest.raises(compat.GitPolicyError, match="git filter discovery failed"):
        compat.run_internal_git(["status", "--porcelain"], repo, timeout=3, check_policy=True)
    assert not executed, "An invalid inherited EOL configuration reached the Git operation"


def test_unreadable_owned_eol_config_refuses_actual_git(owned_repo, tmp_path, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    config = tmp_path / "owned malformed global config"
    config.write_text("[core\n    autocrlf=true\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    with pytest.raises(compat.GitPolicyError, match="git filter discovery failed"):
        compat.run_internal_git(["status", "--porcelain"], repo, timeout=3, check_policy=True)


@pytest.mark.parametrize("value,expected", [("yes", "true"), ("off", "false"), ("input", "input")])
def test_owned_global_eol_aliases_preserve_static_security(value, expected, owned_repo, tmp_path, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    marker = tmp_path / "owned global filter marker"
    config = tmp_path / "owned global EOL and executable config"
    config.write_text(f"[core]\n    autocrlf={value}\n    eol=lf\n", encoding="utf-8")
    subprocess.run([shutil.which("git"), "config", "--file", str(config),
                    "filter.fixture.clean", marker_command(tmp_path, marker)],
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=5, check=True)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    policy = compat.noninteractive_repo_git_env(repo, git_bin=shutil.which("git"), preserve_eol=True)
    assert policy is not None
    configs = {policy[f"GIT_CONFIG_KEY_{i}"]: policy[f"GIT_CONFIG_VALUE_{i}"]
               for i in range(int(policy["GIT_CONFIG_COUNT"]))}
    assert configs["core.autocrlf"] == expected and configs["core.eol"] == "lf"
    assert policy["GIT_CONFIG_GLOBAL"] == __import__("os").devnull
    assert configs["core.hooksPath"] == __import__("os").devnull
    (repo / "tracked.txt").write_text("Owned global EOL content changed\n", encoding="utf-8")
    result = compat.run_internal_git(["diff"], repo, timeout=3, check_policy=True)
    assert result.returncode == 0 and "Owned global EOL content changed" in result.stdout
    assert not marker.exists(), "Preserving EOL settings enabled a global clean filter"


def test_owned_attributes_override_inherited_eol_without_false_dirty(owned_repo, tmp_path, monkeypatch):
    from tools.working_diff import collect_working_diff
    repo, setup = owned_repo
    config = tmp_path / "owned system CRLF config"
    config.write_text("[core]\n    autocrlf=true\n    eol=crlf\n", encoding="utf-8")
    (repo / ".gitattributes").write_text("*.txt text eol=lf\n", encoding="utf-8")
    (repo / "tracked.txt").write_bytes(b"Owned attributes LF baseline\n")
    setup("add", ".gitattributes", "tracked.txt")
    setup("commit", "-m", "Owned LF attributes precedence")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "0")
    result = collect_working_diff(str(repo))
    assert result["success"] and result.get("empty"), "Inherited EOL settings overrode tracked attributes"


@pytest.mark.parametrize("raw,expected", [("autocrlf=", "false"), ("autocrlf", "true")])
def test_owned_eol_empty_and_valueless_boolean_are_distinct(raw, expected, owned_repo, tmp_path, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    config = tmp_path / "owned boolean Git config"
    config.write_text(f"[core]\n    {raw}\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    env = compat.noninteractive_repo_git_env(repo, git_bin=shutil.which("git"), preserve_eol=True)
    assert env is not None
    effective = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
                 for i in range(int(env["GIT_CONFIG_COUNT"]))}
    assert effective["core.autocrlf"] == expected


def test_owned_eol_effective_value_overrides_invalid_lower_priority(owned_repo, tmp_path, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    config = tmp_path / "owned invalid lower priority Git config"
    config.write_text("[core]\n    autocrlf=invalid\n", encoding="utf-8")
    setup("config", "core.autocrlf", "false")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    result = compat.run_internal_git(["status", "--porcelain"], repo, timeout=3, check_policy=True)
    assert result.returncode == 0


@pytest.mark.parametrize('operation', ['stash', 'restore', 'selector'])
def test_update_recovery_policy_refusal_preserves_owned_bytes(operation, owned_repo, tmp_path, monkeypatch):
    import hashlib
    from hermes_cli import _subprocess_compat as compat
    from hermes_cli import update_cmd as owner
    repo, setup = owned_repo
    (repo / 'tracked.txt').write_text('Owned recovery refusal change\n', encoding='utf-8')
    setup('stash', 'push', '-m', 'Owned refusal fixture')
    stash = setup('rev-parse', 'refs/stash').stdout.strip()
    (repo / 'tracked.txt').write_text('Owned current refusal content\n', encoding='utf-8')
    source = tmp_path / 'owned inactive recovery config'
    source.write_text('[include]\n    path=owned-nested-config\n', encoding='utf-8')
    setup('config', 'includeIf.onbranch:inactive-owned-recovery.path', str(source))
    before = hashlib.sha256((repo / 'tracked.txt').read_bytes()).hexdigest()
    executed = []
    probe = compat.bounded_probe_run

    def capture(argv, **kwargs):
        if any(token in argv for token in ('stash','status','reset','diff','ls-files')):
            executed.append(argv)
        return probe(argv, **kwargs)

    monkeypatch.setattr(compat, 'bounded_probe_run', capture)
    with pytest.raises(compat.GitPolicyError, match='git filter discovery failed'):
        if operation == 'stash':
            owner._stash_local_changes_if_needed([shutil.which('git')], repo)
        elif operation == 'restore':
            owner._restore_stashed_changes([shutil.which('git')], repo, stash)
        else:
            owner._resolve_stash_selector([shutil.which('git')], repo, stash)
    assert not executed, 'A refused recovery operation reached Git'
    assert hashlib.sha256((repo / 'tracked.txt').read_bytes()).hexdigest() == before
    assert setup('rev-parse', 'refs/stash').stdout.strip() == stash


def test_owned_unreadable_explicit_config_cannot_be_silently_absent(owned_repo, tmp_path, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    config = tmp_path / "owned unreadable Git config directory"
    config.mkdir()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    executed = []
    probe = compat.bounded_probe_run
    def capture(argv, **kwargs):
        if "status" in argv:
            executed.append(argv)
        return probe(argv, **kwargs)
    monkeypatch.setattr(compat, "bounded_probe_run", capture)
    with pytest.raises(compat.GitPolicyError, match="git filter discovery failed"):
        compat.run_internal_git(["status", "--porcelain"], repo, timeout=3, check_policy=True)
    assert not executed


@pytest.mark.parametrize("value", ["2", "-1"])
def test_owned_numeric_autocrlf_uses_selected_git_boolean_parser(value, owned_repo, tmp_path, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    config = tmp_path / "owned numeric Git boolean config"
    config.write_text(f"[core]\n    autocrlf={value}\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    env = compat.noninteractive_repo_git_env(repo, git_bin=shutil.which("git"), preserve_eol=True)
    assert env is not None
    effective = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
                 for i in range(int(env["GIT_CONFIG_COUNT"]))}
    assert effective["core.autocrlf"] == "true"


@pytest.mark.parametrize("value", ["2", "-1"])
def test_owned_numeric_nosystem_skips_ignored_unreadable_source(value, owned_repo, tmp_path, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    config = tmp_path / "owned ignored system config directory"
    config.mkdir()
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", value)
    result = compat.run_internal_git(["status", "--porcelain"], repo, timeout=3, check_policy=True)
    assert result.returncode == 0


@pytest.mark.parametrize("value,expected", [
    (None, "true"), ("", "false"), ("0", "false"), ("1", "true"),
    ("2", "true"), ("-1", "true"), ("yes", "true"), ("invalid", None),
])
def test_boolean_probe_does_not_parse_repository_input_config(value, expected, owned_repo):
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    setup("config", "core.autocrlf", "input")
    setup("config", "hermes.policyboolean", "invalid")
    before = (repo / ".git" / "config").read_bytes()
    assert compat._git_boolean(value, repo, None, shutil.which("git")) == expected
    assert (repo / ".git" / "config").read_bytes() == before


def test_internal_git_preserves_input_and_neutralizes_filter(owned_repo, tmp_path):
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    setup("config", "core.autocrlf", "input")
    marker = tmp_path / "input-filter-executed"
    setup("config", "filter.fixture.clean", marker_command(tmp_path, marker))
    (repo / "tracked.txt").write_bytes(b"owned changed input\r\n")
    before = (repo / ".git" / "config").read_bytes()
    result = compat.run_internal_git(["add", "--", "tracked.txt"], repo,
                                     timeout=10, check_policy=True)
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert (repo / ".git" / "config").read_bytes() == before
    assert setup("show", ":tracked.txt").stdout == "owned changed input\n"


@pytest.mark.parametrize("source", ["home", "xdg", "missing"])
def test_owned_implicit_global_source_is_not_silently_unreadable(source, owned_repo, tmp_path, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    repo, _ = owned_repo
    home = tmp_path / "owned implicit HOME"
    xdg = tmp_path / "owned implicit XDG"
    home.mkdir()
    xdg.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)
    if source == "home":
        (home / ".gitconfig").mkdir()
    elif source == "xdg":
        (xdg / "git" / "config").mkdir(parents=True)
    if source == "missing":
        result = compat.run_internal_git(["status", "--porcelain"], repo, timeout=3, check_policy=True)
        assert result.returncode == 0
    else:
        with pytest.raises(compat.GitPolicyError, match="git filter discovery failed"):
            compat.run_internal_git(["status", "--porcelain"], repo, timeout=3, check_policy=True)


@pytest.mark.parametrize('reader', ['dump-sha','dump-date','diagnostics','trace','compute-host','host-supervisor'])
def test_metadata_readers_do_not_query_git_after_policy_refusal(reader, owned_repo, tmp_path, monkeypatch):
    import importlib
    import json
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    source = tmp_path / 'owned inactive nested metadata config'
    source.write_text('[include]\n    path=owned-nested-source\n', encoding='utf-8')
    setup('config','includeIf.onbranch:inactive-owned-metadata.path',str(source))
    assert compat.noninteractive_repo_git_env(repo,git_bin=shutil.which('git')) is None
    sha = setup('rev-parse','HEAD').stdout.strip()
    if reader.startswith('dump'):
        from hermes_cli import dump
        if reader == 'dump-sha':
            assert dump._get_git_commit(repo) != sha[:8], 'A refused repository still supplied live Git identity'
        else:
            assert dump._get_git_commit_date(repo) == '', 'A refused repository still supplied a live Git date'
    elif reader == 'diagnostics':
        from hermes_cli import diagnostics_local_export as owner
        monkeypatch.setattr(owner,'__file__',str(repo/'hermes_cli/diagnostics_local_export.py'))
        assert owner.collect_identity_metadata().get('downstream_sha') is None
    elif reader == 'trace':
        from agent.trace_upload import build_trace_jsonl
        output = build_trace_jsonl([{'role':'user','content':'Owned metadata trace fixture'}],
                                  session_id='owned-metadata-fixture',cwd=str(repo))
        assert all(not json.loads(line)['gitBranch'] for line in output.splitlines())
    else:
        name = 'compute_host' if reader == 'compute-host' else 'host_supervisor'
        owner = importlib.import_module('tui_gateway.'+name)
        monkeypatch.setattr(owner,'_repo_root',lambda:repo)
        assert owner._build_sha() == 'unknown'


@pytest.mark.parametrize('reader', ['dump-sha','dump-date','diagnostics','trace','compute-host','host-supervisor'])
def test_metadata_readers_preserve_native_git_identity(reader, owned_repo, monkeypatch):
    import importlib
    import json
    repo, setup = owned_repo
    sha = setup('rev-parse','HEAD').stdout.strip()
    if reader.startswith('dump'):
        from hermes_cli import dump
        if reader == 'dump-sha':
            assert dump._get_git_commit(repo) == sha[:8]
        else:
            date = setup('log','-1','--format=%cd','--date=short','HEAD').stdout.strip()
            assert dump._get_git_commit_date(repo) == date
    elif reader == 'diagnostics':
        from hermes_cli import diagnostics_local_export as owner
        monkeypatch.setattr(owner,'__file__',str(repo/'hermes_cli/diagnostics_local_export.py'))
        assert owner.collect_identity_metadata()['downstream_sha'] == sha
    elif reader == 'trace':
        from agent.trace_upload import build_trace_jsonl
        output = build_trace_jsonl([{'role':'user','content':'Owned positive trace fixture'}],
                                  session_id='owned-positive-fixture',cwd=str(repo))
        assert output and all(json.loads(line)['gitBranch']=='fixture' for line in output.splitlines())
    else:
        name = 'compute_host' if reader == 'compute-host' else 'host_supervisor'
        owner = importlib.import_module('tui_gateway.'+name)
        monkeypatch.setattr(owner,'_repo_root',lambda:repo)
        assert owner._build_sha() == sha


def test_metadata_diagnostics_nonrepo_preserves_explicit_unknown(tmp_path, monkeypatch):
    from hermes_cli import diagnostics_local_export as owner
    root = tmp_path / 'owned nonrepo diagnostics root'
    root.mkdir()
    monkeypatch.setenv('GIT_CEILING_DIRECTORIES', str(tmp_path))
    monkeypatch.setattr(owner,'__file__',str(root/'hermes_cli/diagnostics_local_export.py'))
    metadata = owner.collect_identity_metadata()
    assert 'downstream_sha' in metadata and metadata['downstream_sha'] is None


@pytest.mark.parametrize('reader', ['workspace', 'listing', 'changelog'])
def test_workspace_readers_refuse_unresolved_repository_policy(reader, owned_repo, tmp_path, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    subdir = repo / 'owned workspace child'
    subdir.mkdir()
    (subdir / 'owned visible.txt').write_text('Owned listing content\n', encoding='utf-8')
    source = tmp_path / 'owned inactive workspace config'
    source.write_text('[include]\n    path=owned-nested-config\n', encoding='utf-8')
    setup('config', 'includeIf.onbranch:inactive-owned-workspace.path', str(source))
    setup('update-ref', 'refs/remotes/origin/main', 'HEAD')
    setup('commit', '--allow-empty', '-m', 'Owned ahead fixture')
    setup('update-ref', 'refs/remotes/origin/main', 'HEAD')
    setup('checkout', '--detach', 'HEAD~1')
    assert compat.noninteractive_repo_git_env(repo, git_bin=shutil.which('git')) is None
    if reader == 'workspace':
        from hermes_cli.main import _resolve_workspace_key
        monkeypatch.chdir(subdir)
        assert _resolve_workspace_key() == str(subdir), 'Refused Git supplied a repository identity'
    elif reader == 'listing':
        from tui_gateway import server
        server._fuzzy_cache.clear()
        assert server._list_repo_files(str(subdir)) == [], 'Refusal became a successful file listing'
    else:
        from hermes_cli import web_server
        monkeypatch.setattr(web_server, 'PROJECT_ROOT', repo)
        assert web_server._recent_upstream_commits() == [], 'Refused Git supplied a live changelog'


@pytest.mark.parametrize('reader', ['workspace', 'listing', 'changelog'])
def test_workspace_readers_preserve_native_git_results(reader, owned_repo, monkeypatch):
    repo, setup = owned_repo
    subdir = repo / 'owned workspace child'
    subdir.mkdir()
    (subdir / 'owned 文書.txt').write_text('Owned listing content\n', encoding='utf-8')
    if reader == 'workspace':
        from hermes_cli.main import _resolve_workspace_key
        monkeypatch.chdir(subdir)
        assert _resolve_workspace_key() == str(repo)
    elif reader == 'listing':
        from tui_gateway import server
        server._fuzzy_cache.clear()
        assert server._list_repo_files(str(subdir)) == ['owned 文書.txt']
    else:
        from hermes_cli import web_server
        setup('commit', '--allow-empty', '-m', 'Owned 更新履歴')
        sha = setup('rev-parse', 'HEAD').stdout.strip()
        setup('update-ref', 'refs/remotes/origin/main', 'HEAD')
        setup('checkout', '--detach', 'HEAD~1')
        monkeypatch.setattr(web_server, 'PROJECT_ROOT', repo)
        rows = web_server._recent_upstream_commits(n=1)
        assert len(rows) == 1 and rows[0]['sha'] == sha[:7]
        assert rows[0]['summary'] == 'Owned 更新履歴' and rows[0]['author'] == 'Owned fixture'


def test_workspace_readers_preserve_owned_nonrepo_fallback(tmp_path, monkeypatch):
    from hermes_cli.main import _resolve_workspace_key
    from tui_gateway import server
    root = tmp_path / 'owned nonrepo workspace'
    root.mkdir()
    monkeypatch.setenv('GIT_CEILING_DIRECTORIES', str(tmp_path))
    (root / 'owned 文書.txt').write_text('Owned fallback content\n', encoding='utf-8')
    monkeypatch.chdir(root)
    assert _resolve_workspace_key() == str(root)
    server._fuzzy_cache.clear()
    assert server._list_repo_files(str(root)) == ['owned 文書.txt']


def test_update_recovery_stash_neutralizes_native_clean_filter(owned_repo, tmp_path):
    from hermes_cli.update_cmd import _stash_local_changes_if_needed
    repo, setup = owned_repo
    marker = tmp_path / 'owned updater clean filter marker'
    setup('config', 'filter.fixture.clean', marker_command(tmp_path, marker))
    (repo / 'tracked.txt').write_text('Owned updater local change\n', encoding='utf-8')
    stash = _stash_local_changes_if_needed([shutil.which('git')], repo)
    assert stash, 'Owned local changes were not preserved in a stash'
    assert not marker.exists(), 'Updater recovery executed a repository clean filter'


def test_update_recovery_restore_neutralizes_native_smudge_filter(owned_repo, tmp_path):
    from hermes_cli.update_cmd import _restore_stashed_changes
    repo, setup = owned_repo
    marker = tmp_path / 'owned updater smudge filter marker'
    (repo / 'tracked.txt').write_text('Owned updater restored change\n', encoding='utf-8')
    setup('stash', 'push', '-m', 'Owned recovery fixture')
    stash = setup('rev-parse', 'refs/stash').stdout.strip()
    setup('config', 'filter.fixture.smudge', marker_command(tmp_path, marker))
    assert _restore_stashed_changes([shutil.which('git')], repo, stash)
    assert (repo / 'tracked.txt').read_text(encoding='utf-8') == 'Owned updater restored change\n'
    assert not marker.exists(), 'Updater recovery executed a repository smudge filter'


def test_update_recovery_preserves_native_windows_append_configuration(owned_repo):
    from hermes_cli import _subprocess_compat as compat
    repo, setup = owned_repo
    assert setup('-c', 'windows.appendAtomically=false', 'status', '--porcelain').returncode == 0
    result = compat.run_internal_git(['-c', 'windows.appendAtomically=false', 'status', '--porcelain'],
                                     repo, timeout=5, check_policy=True)
    assert result.returncode == 0


def test_workspace_listing_preserves_nul_delimited_path_bytes(tmp_path, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    from tui_gateway import server
    root = tmp_path / 'owned listing wire fixture'
    root.mkdir()
    name = 'owned a\r\nb.txt'

    def git_result(argv, cwd, **options):
        if 'rev-parse' in argv:
            return subprocess.CompletedProcess(argv, 0, str(root)+'\n', '')
        assert 'ls-files' in argv and '-z' in argv
        wire = (name+'\0').encode('utf-8')
        output = wire if options.get('binary_output') else wire.decode('utf-8').replace('\r\n','\n')
        return subprocess.CompletedProcess(argv, 0, output, '')

    monkeypatch.setattr(compat, 'run_internal_git', git_result)
    server._fuzzy_cache.clear()
    assert server._list_repo_files(str(root)) == [name]


@pytest.mark.parametrize('operation', ['stash', 'restore'])
def test_update_recovery_failed_conflict_probe_cannot_discard_saved_state(operation, owned_repo, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    from hermes_cli import update_cmd as owner
    repo, setup = owned_repo
    content = 'Owned failed-probe recovery content\n'
    (repo / 'tracked.txt').write_text(content, encoding='utf-8')
    setup('stash', 'push', '-m', 'Owned saved recovery fixture')
    stash = setup('rev-parse', 'refs/stash').stdout.strip()
    if operation == 'stash':
        (repo / 'tracked.txt').write_text(content, encoding='utf-8')
    probe = compat.bounded_probe_run

    def failed_conflict_probe(argv, **options):
        if '--unmerged' in argv or '--diff-filter=U' in argv:
            return subprocess.CompletedProcess(argv, 124, '', 'Owned injected probe failure')
        return probe(argv, **options)

    monkeypatch.setattr(compat, 'bounded_probe_run', failed_conflict_probe)
    with pytest.raises(subprocess.CalledProcessError) as error:
        if operation == 'stash':
            owner._stash_local_changes_if_needed([shutil.which('git')], repo)
        else:
            owner._restore_stashed_changes([shutil.which('git')], repo, stash)
    assert error.value.returncode == 124
    assert setup('rev-parse', 'refs/stash').stdout.strip() == stash
    assert (repo / 'tracked.txt').read_text(encoding='utf-8') == content


@pytest.mark.parametrize('stage', ['before-push', 'after-push', 'cleanup-reset'])
def test_update_recovery_late_failure_retains_saved_stash(stage, owned_repo, monkeypatch):
    from hermes_cli import _subprocess_compat as compat
    from hermes_cli import update_cmd as owner
    repo, setup = owned_repo
    saved = 'Owned previously saved recovery content\n'
    (repo / 'tracked.txt').write_text(saved, encoding='utf-8')
    setup('stash', 'push', '-m', 'Owned previous saved fixture')
    stash = setup('rev-parse', 'refs/stash').stdout.strip()
    current = 'Owned current recovery content\n'
    (repo / 'tracked.txt').write_text(current, encoding='utf-8')
    probe = compat.bounded_probe_run
    probes = []
    operations = []

    def fail_late(argv, **options):
        operations.append(argv)
        if 'rev-parse' in argv and 'refs/stash' in argv:
            probes.append(argv)
            if (stage == 'before-push' and len(probes) == 1) or (stage == 'after-push' and len(probes) == 2):
                return subprocess.CompletedProcess(argv, 124, '', 'Owned injected stash probe failure')
        if stage == 'before-push' and 'push' in argv:
            return subprocess.CompletedProcess(argv, 1, '', 'Owned injected push failure')
        if stage == 'cleanup-reset' and 'reset' in argv:
            return subprocess.CompletedProcess(argv, 124, '', 'Owned injected reset failure')
        return probe(argv, **options)

    monkeypatch.setattr(compat, 'bounded_probe_run', fail_late)
    with pytest.raises(subprocess.CalledProcessError) as error:
        if stage == 'cleanup-reset':
            owner._restore_stashed_changes([shutil.which('git')], repo, stash)
        else:
            owner._stash_local_changes_if_needed([shutil.which('git')], repo)
    assert error.value.returncode == 124
    assert not any('drop' in argv for argv in operations)
    if stage == 'before-push':
        assert not any('push' in argv or 'reset' in argv for argv in operations)
        assert (repo / 'tracked.txt').read_text(encoding='utf-8') == current
        assert setup('rev-parse', 'refs/stash').stdout.strip() == stash
    elif stage == 'after-push':
        assert setup('show', 'refs/stash:tracked.txt').stdout == current
    else:
        assert setup('rev-parse', 'refs/stash').stdout.strip() == stash
        assert (repo / 'tracked.txt').read_text(encoding='utf-8') == current


def test_update_recovery_failed_unmerged_reset_stops_before_stash(owned_repo, monkeypatch):
    import hashlib
    from hermes_cli import _subprocess_compat as compat
    from hermes_cli import update_cmd as owner
    repo, setup = owned_repo
    setup('checkout', '-b', 'owned-conflict-side')
    (repo / 'tracked.txt').write_text('Owned conflict side\n', encoding='utf-8')
    setup('add', 'tracked.txt')
    setup('commit', '-m', 'Owned conflict side')
    setup('checkout', 'fixture')
    (repo / 'tracked.txt').write_text('Owned conflict main\n', encoding='utf-8')
    setup('add', 'tracked.txt')
    setup('commit', '-m', 'Owned conflict main')
    with pytest.raises(subprocess.CalledProcessError):
        setup('merge', 'owned-conflict-side')
    before = {p:hashlib.sha256((repo/p).read_bytes()).hexdigest()
              for p in ('tracked.txt','.git/index')}
    probe = compat.bounded_probe_run
    operations = []

    def failed_reset(argv, **options):
        operations.append(argv)
        if 'reset' in argv:
            return subprocess.CompletedProcess(argv, 124, '', 'Owned injected unmerged reset failure')
        return probe(argv, **options)

    monkeypatch.setattr(compat, 'bounded_probe_run', failed_reset)
    with pytest.raises(subprocess.CalledProcessError) as error:
        owner._stash_local_changes_if_needed([shutil.which('git')], repo)
    assert error.value.returncode == 124
    assert not any('push' in argv for argv in operations)
    assert all(hashlib.sha256((repo/p).read_bytes()).hexdigest()==value for p,value in before.items())
