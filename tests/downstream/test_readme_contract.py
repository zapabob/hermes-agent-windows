from __future__ import annotations

from pathlib import Path

from downstream.distribution import load_distribution

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_has_downstream_identity_and_attribution() -> None:
    assert README.startswith("# Hermes Agent Windows Workstation Edition\n")
    assert "Unofficial Windows-native downstream" in README
    assert "Not affiliated with or endorsed by Nous Research" in README
    assert "Hermes Agent is developed by Nous Research under the MIT Licence" in README
    assert "[MIT licence](LICENSE)" in README or "[MIT License](LICENSE)" in README


def test_readme_uses_required_section_order() -> None:
    headings = [
        "## Setup in 30 seconds",
        "## At a glance",
        "## Surfaces",
        "## What's new in 0.23.0",
        "## Why this fork exists",
        "## Architecture in brief",
        "## Ownership & recovery",
        "## Plug-ins & submodules",
        "## Install & Desktop build",
        "## Version & provenance",
        "## Security",
        "## Docs map",
        "## Upstream project",
        "## Licence & attribution",
    ]
    positions = [README.index(heading) for heading in headings]
    assert positions == sorted(positions)


def test_readme_exposes_verified_windows_install_surfaces() -> None:
    normalized = " ".join(README.split())
    assert "git clone https://github.com/zapabob/hermes-agent-windows.git" in README
    assert "https://github.com/zapabob/hermes-agent-windows/releases" in README
    assert "installer" in README.lower()
    assert "portable" in README.lower()
    assert f"**Source version: {load_distribution().version}**" in README
    assert "docs/windows/INSTALL.md" in README
    assert "SHA256SUMS.txt" in README
    assert "curl -fsSL https://raw.githubusercontent.com/NousResearch" not in README
    assert "do not install or endorse this downstream" in normalized
    assert "README.ja.md" in README
    assert "README.zh-CN.md" in README
    assert "## Plug-ins & submodules" in README
    assert "uv run hermes plugins" in README
    assert "docs/windows/INTEGRATIONS.md" in README
    assert "plugins/model-providers/" in README
    assert "production write remains DISABLED" in normalized
    assert "N07-A1" in README
    assert "T06" in README
    assert "T12" in README


def test_readme_preserves_upstream_identity() -> None:
    assert "https://github.com/NousResearch/hermes-agent" in README
    assert "official Windows edition" not in README
    assert "world's largest" not in README


def test_translated_readmes_keep_distribution_metadata_in_parity() -> None:
    localized_quick_start = {
        "README.md": "## Setup in 30 seconds",
        "README.ja.md": "## 30秒でわかる TL;DR と導入",
        "README.zh-CN.md": "## 30 秒看懂：TL;DR 与安装",
    }
    localized_inventory = {
        "README.md": "## Plug-ins & submodules",
        "README.ja.md": "## プラグインとサブモジュール",
        "README.zh-CN.md": "## 插件与子模块",
    }
    for name, quick_start_heading in localized_quick_start.items():
        content = (ROOT / name).read_text(encoding="utf-8")
        for value in (
            "Hermes Agent Windows Workstation Edition",
            "README.md",
            "README.ja.md",
            "README.zh-CN.md",
            "zapabob/hermes-agent-windows",
            "NousResearch/hermes-agent",
            load_distribution().version,
            "b51c055a12220f8c7c18660e8599365012e19532",
            "stable",
            "preview",
            "docs/windows/INSTALL.md",
            "uv sync --locked --all-extras",
            "uv run hermes setup",
            "uv run hermes chat",
            "uv run hermes desktop",
            "uv run hermes plugins",
            "docs/windows/INTEGRATIONS.md",
            "plugins/model-providers/",
            "implementation_router",
            "678a4762b887f3eabe5cad11254b2ab1ae859485",
            "N07-A1",
            "T06",
            "T12",
        ):
            assert value in content, f"{name}: missing {value!r}"
        assert quick_start_heading in content, f"{name}: missing {quick_start_heading!r}"
        assert "TL;DR" in content or "TLDR" in content, f"{name}: missing TL;DR"
        assert localized_inventory[name] in content, f"{name}: missing inventory heading"
