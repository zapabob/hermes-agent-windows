"""Exercise Python package discovery in a populated mixed-language checkout."""

import tomllib
from pathlib import Path
from unittest.mock import patch

from setuptools import find_namespace_packages
import setuptools.discovery


def test_discovery_preserves_namespaces_and_excludes_js_dependency_trees(tmp_path):
    config = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )["tool"]["setuptools"]["packages"]["find"]
    for package in (
        "agent/workers",
        "plugins/example/provider",
        "plugins/example/node_modules/vendor/package",
        "node_modules/vendor/package",
        "apps/frontend/nested",
        "vendor/external/python_namespace",
        "tmp/snapshots/checkout/agent",
    ):
        path = tmp_path / package
        path.mkdir(parents=True)
        (path / "module.py").write_text("", encoding="utf-8")

    visited = []
    walk = setuptools.discovery.os.walk

    def observe_walk(*args, **kwargs):
        for root, directories, files in walk(*args, **kwargs):
            visited.append(Path(root).relative_to(tmp_path).parts)
            yield root, directories, files

    with patch.object(setuptools.discovery.os, "walk", observe_walk):
        packages = find_namespace_packages(str(tmp_path), **config)

    assert "agent.workers" in packages
    assert "plugins.example.provider" in packages
    assert all("node_modules" not in package.split(".") for package in packages)
    assert all(not parts or parts[0] not in {"apps", "vendor", "tmp", "node_modules"} for parts in visited)
