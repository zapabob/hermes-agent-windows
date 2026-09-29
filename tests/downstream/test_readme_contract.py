from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_has_downstream_identity_and_attribution() -> None:
    assert README.startswith("# Hermes Agent Windows Workstation Edition\n")
    assert "An unofficial, Windows-native downstream of Hermes Agent" in README
    assert "This single-maintainer fork is independent of" in README
    assert "not endorsed by, Nous Research" in README
    assert (
        "The original Hermes Agent is developed by Nous Research and licensed under MIT."
        in README
    )


def test_readme_uses_required_section_order() -> None:
    headings = [
        "## 1. Product identity",
        "## 2. Windows-first goals",
        "## 3. Who this is for",
        "## 4. Downstream advantages",
        "## 5. Verified feature matrix",
        "## 6. Windows Tier-1 support contract",
        "## 7. Local AI architecture",
        "## 8. Watchdog and recovery architecture",
        "## 9. Memory and semantic retrieval",
        "## 10. VRChat, Unity, and voice integrations",
        "## 11. Installation",
        "## 12. Update and upstream integration policy",
        "## 13. Architecture",
        "## 14. Security",
        "## 15. Upstream project",
        "## 16. License and attribution",
    ]
    positions = [README.index(heading) for heading in headings]
    assert positions == sorted(positions)


def test_readme_exposes_verified_windows_install_surfaces() -> None:
    normalized = " ".join(README.split())
    assert "git clone https://github.com/zapabob/hermes-agent-windows.git" in README
    assert "https://github.com/zapabob/hermes-agent-windows/releases" in README
    assert "installer" in README.lower()
    assert "portable" in README.lower()
    assert "0.21.5" in README
    assert "docs/windows/INSTALL.md" in README
    assert "curl -fsSL https://raw.githubusercontent.com/NousResearch" not in README
    assert "The official upstream installer targets the upstream distribution" in normalized
    assert "<details open>" in README
    assert "<summary><strong>日本語</strong>" in README
    assert "<summary><strong>简体中文</strong>" in README
    assert "## Plug-ins and Git submodules" in README
    assert "uv run hermes plugins" in README
    assert "docs/windows/INTEGRATIONS.md" in README
    assert "plugins/model-providers/" in README
    assert "production write remains DISABLED" in normalized


def test_readme_preserves_upstream_identity() -> None:
    assert "https://github.com/NousResearch/hermes-agent" in README
    assert "official Windows edition" not in README
    assert "world's largest" not in README


def test_translated_readmes_keep_distribution_metadata_in_parity() -> None:
    localized_quick_start = {
        "README.md": "## Setup in 30 seconds",
        "README.ja.md": "## 30秒でわかる導入",
        "README.zh-CN.md": "## 30 秒看懂安装",
    }
    localized_inventory = {
        "README.md": "## Plug-ins and Git submodules",
        "README.ja.md": "## プラグインとGitサブモジュール",
        "README.zh-CN.md": "## 插件与Git子模块",
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
            "0.21.5",
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
            assert value in content, f"{name}: {value}"
        assert quick_start_heading in content
        assert "TL;DR" in content
        assert localized_inventory[name] in content
