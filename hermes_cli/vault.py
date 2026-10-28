"""``hermes vault`` — manage the local encrypted autofill vault.

Subcommands:
- ``hermes vault add``   interactive wizard; secrets read via getpass (never
  echoed, never accepted as argv).
- ``hermes vault list``  metadata only — labels, kinds, origins, handles.
- ``hermes vault rm``    remove an item by handle/id.
- ``hermes vault key``   where the vault key lives; ``key migrate --to keychain|file`` moves it.

The vault backs the model-blind browser autofill tools
(``browser_vault_list`` / ``browser_vault_fill``): the agent gets opaque
handles and fills login forms server-side without ever seeing the values.
"""

from __future__ import annotations

import getpass


def _console():
    from rich.console import Console

    return Console()


def _cmd_add(args) -> None:
    from agent.vault_store import (
        LOGIN_IDENTIFIER_TYPES,
        VAULT_KINDS,
        VaultError,
        get_vault_store,
    )

    c = _console()
    c.print("[bold]Add a vault item[/] (values are encrypted at rest; the agent never sees them)")

    kind = (args.kind or "").strip().lower()
    while kind not in VAULT_KINDS:
        kind = input(f"Kind ({'/'.join(VAULT_KINDS)}) [login]: ").strip().lower() or "login"
        if kind not in VAULT_KINDS:
            c.print(f"[red]Unknown kind {kind!r}[/]")
            kind = ""

    label = ""
    while not label:
        label = input("Label (e.g. 'GitHub work account'): ").strip()

    try:
        if kind == "login":
            origin = ""
            while not origin:
                origin = input("Site origin (e.g. https://github.com): ").strip()
            id_type = ""
            while id_type not in LOGIN_IDENTIFIER_TYPES:
                id_type = (
                    input(f"Identifier type ({'/'.join(LOGIN_IDENTIFIER_TYPES)}) [email]: ")
                    .strip()
                    .lower()
                    or "email"
                )
            identifier = ""
            while not identifier:
                identifier = input(f"{id_type.capitalize()}: ").strip()
            password = ""
            while not password:
                password = getpass.getpass("Password (hidden): ")
            secret = {
                "identifier_type": id_type,
                "identifier": identifier,
                "password": password,
                "origin": origin,
            }
            meta = get_vault_store().add_item(
                kind="login", label=label, secret=secret, origin=origin
            )
        else:
            c.print(
                f"[dim]{kind} items are stored for future phases; browser fill "
                "currently supports login items only.[/]"
            )
            secret = {}
            c.print("Enter fields one per line as name=value; blank line to finish.")
            c.print("[dim]Values are read hidden (not echoed).[/]")
            while True:
                field = input("Field name (blank to finish): ").strip()
                if not field:
                    break
                secret[field] = getpass.getpass(f"{field} (hidden): ")
            origin = input("Origin (optional, e.g. https://shop.example.com): ").strip() or None
            meta = get_vault_store().add_item(
                kind=kind, label=label, secret=secret, origin=origin
            )
    except VaultError as exc:
        c.print(f"[red]Error:[/] {exc}")
        return

    c.print(f"[green]Stored.[/] handle=[bold]{meta.id}[/] kind={meta.kind} origin={meta.origin or '-'}")


def _cmd_list(args) -> None:
    from agent.vault_store import get_vault_store

    c = _console()
    items = get_vault_store().list_items()
    if not items:
        c.print("[dim]Vault is empty. Add an item with `hermes vault add`.[/]")
        return
    from rich.table import Table

    table = Table(title=f"Vault items ({len(items)})")
    table.add_column("Handle", style="bold")
    table.add_column("Kind")
    table.add_column("Label")
    table.add_column("Origin")
    table.add_column("Created")
    for meta in items:
        table.add_row(meta.id, meta.kind, meta.label, meta.origin or "-", meta.created_at[:19])
    c.print(table)
    c.print("[dim]Values are never shown; the agent only ever receives handles.[/]")


def _cmd_rm(args) -> None:
    from agent.vault_store import get_vault_store

    c = _console()
    if get_vault_store().remove_item(args.handle):
        c.print(f"[green]Removed[/] {args.handle}")
    else:
        c.print(f"[red]No vault item with handle {args.handle!r}[/]")


def _cmd_key(args) -> None:
    """Show where the local vault's key lives, or move it between vault.key and the OS keychain."""
    from agent import vault_keychain
    from agent.vault_store import configured_key_storage, get_vault_store

    c = _console()
    store = get_vault_store()
    target = getattr(args, "to", None)
    if target:
        if target == "keychain" and not _ensure_keychain_extra(c):
            return
        # A failed move raises VaultError before the setting changes: the original storage stays.
        store.migrate_key(target)
        _set_key_storage(target)
        if store.key_location()["storage"] == "none":  # nothing was moved or verified, only the setting
            c.print(f"No vault key exists yet. The first saved item creates one in "
                    f"{'the OS keychain' if target == 'keychain' else 'vault.key'} (vault.key_storage = {target}).")
        elif target == "keychain":
            c.print(f"[green]Vault key moved to the OS keychain[/] ({vault_keychain.backend_label()}); "
                    "vault.key was removed after the keychain copy decrypted the vault.")
            c.print("[dim]Backups of this profile now hold the encrypted vault without its key (it is not "
                    "exported to another PC); `hermes vault key migrate --to file` before moving the "
                    "profile to another machine or an older Hermes.[/]")
        else:
            where = store.key_location()
            c.print(f"[green]Vault key moved to[/] {where.get('path')} (owner-only).")
            if where.get("keychain_entry_left"):
                c.print(f"[yellow]The keychain copy ({where['keychain_entry_left']}) could not be removed yet;[/] "
                        "run this command again when the keychain is reachable.")
            else:
                c.print("Keychain entry removed.")
        return
    where = store.key_location()
    if where["storage"] == "file":
        c.print(f"Vault key: [bold]file[/] {where['path']} (owner-only, beside the encrypted vault)")
        if where.get("keychain_entry_left"):
            c.print("[yellow]A keychain copy is still recorded; run `hermes vault key migrate --to file` to clear it.[/]")
    elif where["storage"] == "keychain":
        c.print(f"Vault key: [bold]OS keychain[/] service {where.get('service')!r}, account {where['account']!r}")
    else:
        c.print("Vault key: [dim]none yet[/] (created with the first saved item)")
    c.print(f"New vaults use: vault.key_storage = {configured_key_storage()}")
    c.print(f"OS keychain here: {vault_keychain.backend_label()}")


def _ensure_keychain_extra(c) -> bool:
    """Lazy-install the ``keychain`` extra (``keyring``) before migrating to OS keychain.

    Mirrors upstream ``pm.extras.ensure_import("keychain")`` using this fork's
    ``tools.lazy_deps`` allowlist (``vault.keychain``). Returns False when the
    install is blocked or fails so the CLI can abort without mutating config.
    """
    from tools.lazy_deps import FeatureUnavailable, ensure, is_available

    if is_available("vault.keychain"):
        return True
    try:
        ensure("vault.keychain", prompt=True)
    except FeatureUnavailable as exc:
        c.print(f"[red]The keychain feature is not installed:[/] {exc}")
        c.print("[dim]Install with: uv sync --extra keychain[/]")
        return False
    return True


def _set_key_storage(value: str) -> None:
    from hermes_cli.config import load_config, save_config

    cfg = load_config()
    section = cfg.get("vault")
    if not isinstance(section, dict):
        section = {}
        cfg["vault"] = section
    section["key_storage"] = value
    save_config(cfg)


def register_cli(subparser) -> None:
    """Build the ``hermes vault`` argparse tree (called from main.py)."""
    subs = subparser.add_subparsers(dest="vault_action")

    p_add = subs.add_parser(
        "add",
        help="Add a credential to the vault (interactive; secrets never echoed)",
    )
    p_add.add_argument(
        "--kind", choices=["login", "payment", "address"], default=None,
        help="Item kind (interactive prompt when omitted)",
    )
    p_add.set_defaults(_vault_handler=_cmd_add)

    p_list = subs.add_parser("list", help="List vault items (metadata only, never values)")
    p_list.set_defaults(_vault_handler=_cmd_list)

    p_rm = subs.add_parser("rm", help="Remove a vault item by handle")
    p_rm.add_argument("handle", help="Item handle (see `hermes vault list`)")
    p_rm.set_defaults(_vault_handler=_cmd_rm)

    p_key = subs.add_parser("key", help="Show where the local vault key is stored (vault.key file or OS keychain)")
    p_key.set_defaults(_vault_handler=_cmd_key, to=None)
    key_subs = p_key.add_subparsers(dest="vault_key_action")
    p_migrate = key_subs.add_parser(
        "migrate", help="Move the vault key to the OS keychain or back to vault.key (verified before the old copy is removed)")
    p_migrate.add_argument("--to", choices=["keychain", "file"], required=True, help="Destination for the key")
    p_migrate.set_defaults(_vault_handler=_cmd_key)


def vault_command(args) -> None:
    from agent.vault_store import VaultError

    handler = getattr(args, "_vault_handler", None)
    try:
        if handler is None:
            _cmd_list(args)
            return
        handler(args)
    except VaultError as exc:
        _console().print(f"[red]Error:[/] {exc}")
        raise SystemExit(1) from exc
