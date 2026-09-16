"""Source typechecks must work before declaration outputs have been built."""
from __future__ import annotations

import json
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[2] / "apps" / "desktop"


def test_source_typecheck_inherits_compiler_policy_without_build_references() -> None:
    base = json.loads((DESKTOP / "tsconfig.json").read_text(encoding="utf-8"))
    check = json.loads((DESKTOP / "tsconfig.typecheck.json").read_text(encoding="utf-8"))
    # Only project-output redirection changes. Strictness, include/exclude, and
    # path aliases remain inherited; the production build graph is untouched.
    assert check == {"extends": "./tsconfig.json", "references": []}
    assert base["compilerOptions"]["strict"] is True
    assert base["references"] == [
        {"path": "./tsconfig.electron.json"},
        {"path": "./tsconfig.e2e.json"},
    ]


def test_typecheck_still_checks_renderer_electron_and_e2e_without_emit() -> None:
    package = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["typecheck"].split(" && ") == [
        "tsc -p tsconfig.typecheck.json --noEmit",
        "tsc -p tsconfig.electron.json --noEmit",
        "tsc -p tsconfig.e2e.json --noEmit",
    ]
