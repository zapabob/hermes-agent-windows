"""Public /new with the same ordinary agent refreshes only new-session skills."""
from datetime import datetime

import pytest

from tests.agent.test_skills_auto_load_native import MARKER, OTHER, native, prompt


@pytest.mark.parametrize("change", ["file", "config", "disabled", "deleted"])
def test_same_agent_public_new_reloads_skills(native, monkeypatch, change):
    import cli
    instance = native.agent()
    initial = prompt(instance)
    assert initial.count(MARKER) == 1
    cached = instance._auto_load_skills_result
    shell = cli.HermesCLI.__new__(cli.HermesCLI)
    shell.agent = instance
    shell.session_id = instance.session_id
    shell.session_start = datetime.now()
    shell.conversation_history = []
    shell._session_db = instance._session_db
    shell._auto_load_skills_result = cached
    shell.model = instance.model
    shell.provider = instance.provider
    shell.base_url = instance.base_url
    shell.api_key = instance.api_key
    shell.max_turns = 2
    shell.config = {}
    shell._write_terminal_breadcrumb = lambda: None
    monkeypatch.setattr(cli, "CLI_CONFIG", {"agent": {}, "model": {"default": instance.model}})
    monkeypatch.setenv("HERMES_SESSION_ID", instance.session_id)
    if change == "file":
        native.skill(body=OTHER)
    elif change == "config":
        native.skill(name="native-beta", body=OTHER)
        native.config({"skills": {"auto_load": ["native-beta"]}})
    elif change == "disabled":
        native.config({"skills": {"auto_load": ["native-alpha"], "disabled": ["native-alpha"]}})
    else:
        (native.home / "skills/native-alpha/SKILL.md").unlink()
    # In-session rebuilding must keep the captured bytes.
    assert prompt(instance).count(MARKER) == 1
    old_session = shell.session_id
    assert shell.process_command("/new now") is True
    assert shell.agent is instance
    assert shell.session_id != old_session
    assert instance.session_id == shell.session_id
    after = prompt(instance)
    assert MARKER not in after
    assert after.count(OTHER) == (1 if change in {"file", "config"} else 0)
    assert shell._auto_load_skills_result is None, "startup handoff remains stale"
    assert shell._session_db.get_session(shell.session_id) is not None
