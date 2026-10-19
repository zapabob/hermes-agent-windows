"""Python package markers must not split one project into multiple LSPs."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

from agent.lsp.manager import LSPService
from agent.lsp.servers import SERVERS, ServerContext, SpawnSpec, _root_python, _root_typescript
from agent.lsp.workspace import clear_cache, nearest_root


def package_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a real project and a package containing a setup module."""
    root = tmp_path / "project 日本語"
    package = root / "package"
    package.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='owned'\n", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "setup.py").write_text("# ordinary package module\n", encoding="utf-8")
    nested = package / "nested.py"
    nested.write_text("broken()\n", encoding="utf-8")
    top = root / "top.py"
    top.write_text("broken()\n", encoding="utf-8")
    return root, top, nested


def test_python_package_setup_py_does_not_split_project(tmp_path: Path) -> None:
    root, top, nested = package_tree(tmp_path)
    assert _root_python(str(top), str(root)) == str(root)
    assert _root_python(str(nested), str(root)) == str(root)


def test_non_python_project_in_package_retains_its_root(tmp_path: Path) -> None:
    root, _, nested = package_tree(tmp_path)
    package = nested.parent
    (package / "package.json").write_text("{}", encoding="utf-8")
    # The upstream generic skip would silently change TypeScript as well.
    assert _root_typescript(str(package / "app.ts"), str(root)) == str(package)
    assert nearest_root(str(nested), ["setup.py"], ceiling=str(root)) == str(package)


def test_real_nested_python_project_keeps_its_own_client_root(tmp_path: Path) -> None:
    root, _, nested = package_tree(tmp_path)
    project = root / "independent"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='child'\n", encoding="utf-8")
    assert _root_python(str(project / "app.py"), str(root)) == str(project)
    assert _root_python(str(nested), str(root)) == str(root)


@pytest.mark.parametrize("exclude", ["deno.json", "disabled.marker"])
def test_package_skip_still_honors_excludes_and_ceiling(tmp_path: Path, exclude: str) -> None:
    root, _, nested = package_tree(tmp_path)
    (nested.parent / exclude).write_text("{}", encoding="utf-8")
    assert nearest_root(str(nested), ["pyproject.toml"], excludes=[exclude],
                        ceiling=str(root), skip_python_packages=True) is None
    # A matching marker beyond the ceiling makes removing the bound fail.
    (tmp_path / "absent.marker").write_text("", encoding="utf-8")
    assert nearest_root(str(nested), ["absent.marker"], ceiling=str(root),
                        skip_python_packages=True) is None
    assert nearest_root(str(nested), ["absent.marker"],
                        skip_python_packages=True) == str(tmp_path)


def test_python_without_project_markers_falls_back_to_workspace(tmp_path: Path) -> None:
    root, _, nested = package_tree(tmp_path)
    (root / "pyproject.toml").unlink()
    assert _root_python(str(nested), str(root)) == str(root)


def test_package_diagnostics_reuse_one_real_stdio_client(tmp_path: Path, monkeypatch) -> None:
    root, top, nested = package_tree(tmp_path)
    monkeypatch.chdir(root)
    clear_cache()
    index = next(i for i, server in enumerate(SERVERS) if server.server_id == "pyright")
    original = SERVERS[index]
    spawned: list[str] = []
    peer = str(Path(__file__).with_name("_mock_lsp_server.py"))

    def spawn(project: str, context: ServerContext) -> SpawnSpec:
        spawned.append(project)
        return SpawnSpec(command=[sys.executable, "-B", peer], workspace_root=project,
                         cwd=project, env={"MOCK_LSP_SCRIPT": "errors"})

    # Only replace the external language engine. Root resolution, manager,
    # real child, client, framing and diagnostic delivery remain in use.
    monkeypatch.setattr(original, "build_spawn", spawn)
    service = LSPService(enabled=True, wait_mode="document", install_strategy="manual",
                         wait_timeout=3.0, idle_timeout=0)
    try:
        for file in (top, nested):
            diagnostics = service.get_diagnostics_sync(str(file))
            assert diagnostics and diagnostics[0]["code"] == "MOCK001"
        assert spawned == [str(root)]
        assert list(service._clients) == [("pyright", str(root))]
    finally:
        service.shutdown()
        clear_cache()
    assert not service._clients
