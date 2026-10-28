"""Read a plugin's native manifest without importing CLI configuration or plugin code.

Subset of upstream's ``pm.plugin_declarations``: only the manifest readers the plugin OAuth broker needs
(``native_manifest_file`` and ``read_native_manifest``). Python-declaration, requirement and manifest-version
helpers are out of scope here and arrive with the plugin-manager port.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def native_manifest_file(plugin_dir: Path) -> Path | None:
    """``plugin.yaml`` (else ``plugin.yml``) of *plugin_dir*, or None when it has neither."""
    for path in (plugin_dir / "plugin.yaml", plugin_dir / "plugin.yml"):
        try:
            path.stat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError(f"Could not inspect plugin manifest {path}: {exc}") from exc
        return path
    return None


def read_native_manifest(path: Path) -> dict:
    """The manifest mapping at *path* (empty for an empty file); ``ValueError`` when it cannot be read."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not read plugin manifest {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Plugin manifest must be a mapping: {path}")
    return data


__all__ = ["native_manifest_file", "read_native_manifest"]
