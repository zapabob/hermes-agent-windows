"""Fresh clones must use the bounded owner and an empty Git template."""
import shlex
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
from hermes_cli import plugins_cmd as plugin, profile_distribution as distribution, mcp_catalog as catalog
from hermes_cli._subprocess_compat import noninteractive_git_env


@pytest.fixture
def owned_source(tmp_path):
    git = shutil.which("git")
    assert git
    repo = tmp_path / "source"
    repo.mkdir()
    def setup(*args):
        return subprocess.run([git, *args], cwd=repo, env=noninteractive_git_env(),
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", timeout=10, check=True)
    setup("init", "-q")
    setup("config", "user.name", "Fixture")
    setup("config", "user.email", "fixture@example.invalid")
    (repo / "plugin.yaml").write_text("name: owned-fixture\nversion: 1.0.0\n", encoding="utf-8")
    (repo / "owned.txt").write_bytes(b"owned clone content\n")
    (repo / ".gitattributes").write_text("owned.txt -text filter=fixture\n", encoding="utf-8")
    setup("add", ".")
    setup("commit", "-qm", "Owned source")
    return repo, setup("rev-parse", "HEAD").stdout.strip()


@pytest.mark.parametrize("surface", ["plugin", "distribution", "catalog"])
def test_fresh_clone_never_executes_ambient_template_smudge(tmp_path, monkeypatch, owned_source, surface):
    repo, revision = owned_source
    marker = tmp_path / "template-smudge-executed"
    script = tmp_path / "owned-smudge.py"
    script.write_text("import pathlib,sys\n" +
        f"pathlib.Path({str(marker)!r}).write_text('FIXTURE',encoding='utf-8')\n" +
        "sys.stdout.buffer.write(sys.stdin.buffer.read())\n", encoding="utf-8")
    command = " ".join(shlex.quote(value.replace("\\", "/")) for value in (sys.executable, "-I", str(script)))
    template = tmp_path / "owned-template"
    template.mkdir()
    (template / "config").write_text('[filter "fixture"]\nsmudge = ' + command.replace("\\", "\\\\").replace('"', '\\"') + '\n', encoding="utf-8")
    before = (template / "config").read_bytes()
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(template))
    if surface == "plugin":
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
        monkeypatch.setattr(plugin, "_scan_plugin_tree", lambda *a, **kw: None)
        dest, _, _ = plugin._install_plugin_core(repo.as_uri(), force=False)
    elif surface == "distribution":
        dest = tmp_path / "distribution"
        distribution._git_clone(repo.as_uri(), dest)
    else:
        root = tmp_path / "catalog"
        root.mkdir()
        monkeypatch.setattr(catalog, "_install_root", lambda: root)
        entry = SimpleNamespace(name="fixture", install=SimpleNamespace(type="git", url=repo.as_uri(), ref=revision, bootstrap=[]))
        dest = catalog._do_git_install(entry)
    assert (dest / "owned.txt").read_bytes() == b"owned clone content\n"
    assert not marker.exists()
    assert (template / "config").read_bytes() == before


def test_profile_clone_timeout_is_typed_and_does_not_retry(tmp_path, monkeypatch):
    calls = []
    def unavailable(*args, **kwargs):
        calls.append(args)
        return None
    monkeypatch.setattr("hermes_cli._subprocess_compat.bounded_probe_run", unavailable)
    monkeypatch.setattr(distribution.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, b"", b""))
    with pytest.raises(distribution.DistributionError, match="timed out"):
        distribution._git_clone("file:///owned-fixture", tmp_path / "clone")
    assert len(calls) == 1


def test_pinned_checkout_neutralizes_existing_repository_smudge(tmp_path, monkeypatch, owned_source):
    from hermes_cli._subprocess_compat import clone_git_repository
    repo, revision = owned_source
    clone = tmp_path / "clone"
    git = shutil.which("git")
    result = clone_git_repository(repo.as_uri(), clone, timeout=15, git_bin=git, no_checkout=True)
    assert result.returncode == 0, result.stderr
    marker = tmp_path / "pinned-smudge-executed"
    script = tmp_path / "pinned-smudge.py"
    script.write_text("import pathlib,sys\n" + f"pathlib.Path({str(marker)!r}).write_text('FIXTURE',encoding='utf-8')\n" + "sys.stdout.buffer.write(sys.stdin.buffer.read())\n", encoding="utf-8")
    command = " ".join(shlex.quote(value.replace("\\", "/")) for value in (sys.executable, "-I", str(script)))
    subprocess.run([git, "config", "filter.fixture.smudge", command], cwd=clone,
                   env=noninteractive_git_env(), stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=True)
    before = (clone / ".git" / "config").read_bytes()
    assert not (clone / "owned.txt").exists()
    plugin._checkout_exact_revision(clone, git, revision)
    assert not marker.exists()
    assert (clone / "owned.txt").read_bytes() == b"owned clone content\n"
    assert (clone / ".git" / "config").read_bytes() == before
