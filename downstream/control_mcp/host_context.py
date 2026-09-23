"""Carry only the resolved Hermes profile path into trusted host threads."""
from __future__ import annotations

from hermes_constants import reset_hermes_home_override, set_hermes_home_override


def run_with_profile_home(profile_home, fn, *args):
    token = set_hermes_home_override(profile_home)
    try:
        return fn(*args)
    finally:
        reset_hermes_home_override(token)
