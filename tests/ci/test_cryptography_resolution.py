"""Keep package metadata and the security override on the same locked pin."""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement


def test_cryptography_override_preserves_declared_exact_pin():
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))

    def requirement(entries):
        return next(req for entry in entries if (req := Requirement(entry)).name == "cryptography")

    declared = requirement(project["project"]["dependencies"])
    override = requirement(project["tool"]["uv"]["override-dependencies"])
    locked = next(pkg["version"] for pkg in lock["package"] if pkg["name"] == "cryptography")
    assert str(declared.specifier) == f"=={locked}"
    # uv overrides the root requirement too. A range here silently installs a
    # newer version while leaving incompatible Requires-Dist in built metadata.
    assert override.specifier == declared.specifier
