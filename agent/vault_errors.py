"""Shared exception for the local vault (kept apart so the key-storage module can raise it
without importing ``agent.vault_store``, which imports that module)."""

from __future__ import annotations


class VaultError(Exception):
    """Vault failure that is safe to surface (never contains secret values)."""
