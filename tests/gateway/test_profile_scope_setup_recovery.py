"""A raise mid-scope-setup must release whatever was already bound.

A leaked HERMES_HOME override or secret scope silently re-homes every later
read in the caller's context (config, skills, memory and credentials).
"""

import pytest

from agent import secret_scope
from hermes_constants import get_hermes_home_override


def _boom(*_args, **_kwargs):
    raise RuntimeError("corrupt profile home")


@pytest.mark.parametrize(
    "failing_target",
    [
        "agent.secret_scope.build_profile_secret_scope",
        "hermes_cli.env_loader.hydrate_profile_secret_sources",
    ],
)
def test_profile_runtime_scope_setup_failure_restores_context(monkeypatch, tmp_path, failing_target):
    from gateway.run import _profile_runtime_scope

    foreign = tmp_path / "profiles" / "b"
    foreign.mkdir(parents=True)
    monkeypatch.setattr(failing_target, _boom)

    with pytest.raises(RuntimeError, match="corrupt profile home"):
        with _profile_runtime_scope(foreign):
            pytest.fail("body must not run when scope setup raises")

    assert get_hermes_home_override() is None
    assert secret_scope.current_secret_scope() is None


def test_profile_runtime_scope_binds_and_releases(tmp_path):
    from gateway.run import _profile_runtime_scope

    foreign = tmp_path / "profiles" / "b"
    foreign.mkdir(parents=True)
    (foreign / ".env").write_text("SCOPED_KEY=from-b\n", encoding="utf-8")

    with _profile_runtime_scope(foreign):
        assert get_hermes_home_override() == str(foreign)
        assert secret_scope.get_secret("SCOPED_KEY") == "from-b"

    assert get_hermes_home_override() is None
    assert secret_scope.current_secret_scope() is None
