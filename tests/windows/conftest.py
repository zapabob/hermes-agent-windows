"""Explicit approval switches for Windows tests with per-user OS state."""

from __future__ import annotations


def pytest_addoption(parser):
    group = parser.getgroup("t06 native boundary")
    group.addoption(
        "--allow-t06-ephemeral-appcontainer-profile",
        action="store_true",
        default=False,
        help=(
            "create and delete the T06 test AppContainer profile under the current user's "
            "Windows Packages/AppData profile storage"
        ),
    )
    group.addoption(
        "--t06-confirm-appcontainer-profile",
        action="store",
        default="",
        help="exact fixed profile name required by the gated T06 profile experiment",
    )
